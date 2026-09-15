"""RSSI models and bounded weighted nonlinear least squares, in metres."""
import math
import statistics


def distance_from_rssi(rssi, intercept=-59.0, n=2.2):
    if n <= 0 or not all(math.isfinite(x) for x in (rssi, intercept, n)):
        raise ValueError("Invalid path-loss model")
    return max(0.15, min(50.0, 10 ** max(-2, min(2, (intercept-rssi)/(10*n)))))


def filtered_rssi(values, floor=4.0):
    median = statistics.median(values)
    mad = statistics.median(abs(x-median) for x in values)
    kept = [x for x in values if abs(x-median) <= max(3.0, 3*1.4826*mad)]
    return statistics.mean(kept), max(floor, statistics.variance(kept) if len(kept) > 1 else floor)


def channel_distance(rssi, variance, intercept, n):
    d = distance_from_rssi(rssi, intercept, n)
    # Delta-method approximation; not an accuracy bound in multipath.
    return d, max(0.04, (math.log(10)*d/(10*n))**2*variance)


def fuse_distances(estimates):
    weights = [1/max(v, 0.04) for _, v in estimates]
    total = sum(weights)
    mean = sum(w*d for w, (d, _) in zip(weights, estimates))/total
    # Channels share environmental errors: do not claim 1/N noise reduction.
    variance = sum(w*(v+(d-mean)**2) for w, (d, v) in zip(weights, estimates))/total
    return mean, variance


def trilaterate(anchors, distances, variances=None, bounds=None):
    """Damped Gauss-Newton with line search; returns fit diagnostics, no clipping fiction."""
    if len(anchors) < 3 or len(anchors) != len(distances):
        raise ValueError("At least three matching anchors required")
    if any(not math.isfinite(d) or d <= 0 for d in distances):
        raise ValueError("Distances must be finite and positive")
    area = max(abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
               for a in anchors for b in anchors for c in anchors)
    if area < 1e-6:
        raise ValueError("Collinear anchors")
    variances = variances if variances is not None else [1.0]*len(anchors)
    if len(variances) != len(anchors) or any(not math.isfinite(v) or v <= 0 for v in variances):
        raise ValueError("Invalid distance variances")
    weights = [1/max(v, 0.04) for v in variances]
    def cost(x, y):
        return sum(w*(math.hypot(x-a, y-b)-d)**2 for (a,b),d,w in zip(anchors,distances,weights))
    def solve(start):
        x,y = start
        for _ in range(60):
            hxx=hyy=1e-4
            hxy=gx=gy=0.0
            for (a,b),d,w in zip(anchors,distances,weights):
                r=max(math.hypot(x-a,y-b), 1e-6)
                jx,jy=(x-a)/r,(y-b)/r
                hxx+=w*jx*jx; hyy+=w*jy*jy; hxy+=w*jx*jy
                gx+=w*jx*(r-d); gy+=w*jy*(r-d)
            det=hxx*hyy-hxy*hxy
            if det < 1e-12:
                break
            dx,dy=-(hyy*gx-hxy*gy)/det,-(hxx*gy-hxy*gx)/det
            before=cost(x,y)
            step=1.0
            for _ in range(16):
                nx,ny=x+step*dx,y+step*dy
                if bounds:
                    nx,ny=max(0,min(bounds[0],nx)),max(0,min(bounds[1],ny))
                if cost(nx,ny) <= before:
                    break
                step*=0.5
            if cost(nx,ny) > before:
                break
            moved=math.hypot(nx-x,ny-y)
            x,y=nx,ny
            if moved < 1e-6:
                break
        return x,y,cost(x,y)
    center=(statistics.mean(a[0] for a in anchors),statistics.mean(a[1] for a in anchors))
    starts=[center]+[((a[0]+center[0])/2,(a[1]+center[1])/2) for a in anchors]
    x,y,c=min((solve(s) for s in starts),key=lambda r:r[2])
    residual=math.sqrt(sum((math.hypot(x-a,y-b)-d)**2 for (a,b),d in zip(anchors,distances))/len(anchors))
    # Local information inverse inflated by inconsistent circles.
    xx=yy=1e-6; xy=0.0
    for (a,b),w in zip(anchors,weights):
        r=max(math.hypot(x-a,y-b),1e-6)
        jx,jy=(x-a)/r,(y-b)/r
        xx+=w*jx*jx; yy+=w*jy*jy; xy+=w*jx*jy
    det=max(xx*yy-xy*xy,1e-9)
    return {"x":x,"y":y,"residual_m":residual,"variance_x":yy/det+residual**2,
            "variance_y":xx/det+residual**2,"at_boundary":bool(bounds and (min(x,y)<0.001 or x>bounds[0]-.001 or y>bounds[1]-.001))}


class AxisKalman:
    """Constant-velocity 2-state filter; measurement variance adapts to innovation."""
    def __init__(self, value):
        self.x,self.v=value,0.0
        self.p00,self.p01,self.p11=4.0,0.0,4.0

    def update(self, measurement, dt, variance, q):
        self.x += self.v*dt
        a=self.p00+2*dt*self.p01+dt*dt*self.p11+q*dt**4/4
        b=self.p01+dt*self.p11+q*dt**3/2
        c=self.p11+q*dt*dt
        innovation=measurement-self.x
        r=max(0.04,variance,innovation**2/9-a)
        k0,k1=a/(a+r),b/(a+r)
        self.x+=k0*innovation; self.v+=k1*innovation
        self.p00=(1-k0)*a; self.p01=(1-k0)*b; self.p11=c-k1*b
        return self.x
