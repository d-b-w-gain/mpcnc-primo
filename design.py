"""MPCNC Primo (J, 25.4 mm tube) - full assembly from V1 Engineering's own parts.

Printed parts are V1's J STLs (github.com/V1EngineeringInc/MPCNC_Primo and
MPCNC_Primo_Tool_Mounts, CC BY-NC-SA 4.0), decimated to a 0.35 mm grid and
stored in meshes.json. Each part is placed from its own geometry: tube bores,
bearing bolt holes and mating faces measured from the STLs (see README.md).
Tube lengths come from V1's cut calculator (primo_calc.py).

World frame: X right, Y back, Z up, table top at Z=0, 0,0 corner front-left.
"""
import base64
import json
import math
import zlib
from array import array
from pathlib import Path

import build123d as bd
from OCP.BRep import BRep_Builder
from OCP.gp import gp_Dir, gp_Pnt
from OCP.Poly import Poly_Triangle, Poly_Triangulation
from OCP.TopoDS import TopoDS_Face

from primo_calc import cut_list, load_params

P = load_params()
C = cut_list(P)
HERE = Path(__file__).parent
R_TUBE = P["tube_od"] / 2
S2 = math.sqrt(0.5)

COL = {k: bd.Color(*v) for k, v in P["colors"].items()}
STEEL = bd.Color(0.72, 0.74, 0.77)
MOTOR = bd.Color(0.08, 0.08, 0.08)
SPINDLE = bd.Color(0.85, 0.85, 0.88)
TABLE = bd.Color(0.76, 0.62, 0.42)
WORK = bd.Color(0.55, 0.85, 0.55)   # opaque: the viewer skips transparent materials

# ---- rigid transforms: (R rows, t), p' = R p + t -------------------------


def frame(cols, local, world):
    """Transform whose rotation has the given column images and maps point `local` to `world`."""
    R = [[cols[c][r] for c in range(3)] for r in range(3)]
    Rl = [sum(R[r][k] * local[k] for k in range(3)) for r in range(3)]
    return R, [world[r] - Rl[r] for r in range(3)]


def compose(a, b):
    """a after b."""
    Ra, ta = a
    Rb, tb = b
    R = [[sum(Ra[r][k] * Rb[k][c] for k in range(3)) for c in range(3)] for r in range(3)]
    t = [sum(Ra[r][k] * tb[k] for k in range(3)) + ta[r] for r in range(3)]
    return R, t


def apply(T, p):
    R, t = T
    return [sum(R[r][k] * p[k] for k in range(3)) + t[r] for r in range(3)]


def det(R):
    return (R[0][0] * (R[1][1] * R[2][2] - R[1][2] * R[2][1])
            - R[0][1] * (R[1][0] * R[2][2] - R[1][2] * R[2][0])
            + R[0][2] * (R[1][0] * R[2][1] - R[1][1] * R[2][0]))


def rot_z(deg, about_local, to_world, dz=0.0):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return frame([(c, s, 0), (-s, c, 0), (0, 0, 1)], (*about_local, 0), (*to_world, dz))


# ---- meshes ---------------------------------------------------------------
_mesh_cache, _array_cache = {}, {}


def _arrays(name):
    """Vertices (mm, flat list) and triangle indices of mesh_<name>.json (meshpack format)."""
    if name not in _array_cache:
        doc = json.loads((HERE / f"mesh_{name}.json").read_text())
        q = array("h")
        q.frombytes(zlib.decompress(base64.b64decode(doc["v"])))
        o, s = doc["origin"], doc["q"]
        v = [q[i] * s + o[i % 3] for i in range(len(q))]
        f = array(doc["itype"])
        f.frombytes(zlib.decompress(base64.b64decode(doc["f"])))
        _array_cache[name] = (v, f)
    return _array_cache[name]


def mesh(name, mirror=False):
    """V1 part as a build123d face carrying its triangulation; `mirror` reflects it in X
    (V1's 'Mirrored' parts). Normals are smooth but creased at edges sharper than 35 deg,
    so every part exports with NORMALs like the B-rep parts do - the Tertius viewer merges
    all meshes into one geometry and drops it if some lack normals."""
    key = (name, mirror)
    if key not in _mesh_cache:
        v, f = _arrays(name)
        sx = -1.0 if mirror else 1.0
        n = len(f) // 3
        tris, tnorm = [], []
        for t in range(n):
            a, b, c = f[3 * t], f[3 * t + 1], f[3 * t + 2]
            if mirror:
                b, c = c, b
            pa = (sx * v[3 * a], v[3 * a + 1], v[3 * a + 2])
            pb = (sx * v[3 * b], v[3 * b + 1], v[3 * b + 2])
            pc = (sx * v[3 * c], v[3 * c + 1], v[3 * c + 2])
            e1 = [pb[k] - pa[k] for k in range(3)]
            e2 = [pc[k] - pa[k] for k in range(3)]
            cr = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
            ln = math.sqrt(cr[0] ** 2 + cr[1] ** 2 + cr[2] ** 2)
            if ln == 0:
                continue
            tris.append((a, b, c))
            tnorm.append((cr[0] / ln, cr[1] / ln, cr[2] / ln, ln))
        # smoothing groups per vertex: (accumulated normal, first normal, node id)
        groups = {}
        nodes, normals, out = [], [], []
        for t, (a, b, c) in enumerate(tris):
            nx, ny, nz, w = tnorm[t]
            ids = []
            for vi in (a, b, c):
                for g in groups.setdefault(vi, []):
                    if g[1][0] * nx + g[1][1] * ny + g[1][2] * nz > 0.82:
                        g[0][0] += nx * w
                        g[0][1] += ny * w
                        g[0][2] += nz * w
                        ids.append(g[2])
                        break
                else:
                    g = [[nx * w, ny * w, nz * w], (nx, ny, nz), len(nodes)]
                    groups[vi].append(g)
                    nodes.append((sx * v[3 * vi], v[3 * vi + 1], v[3 * vi + 2]))
                    normals.append(g[0])
                    ids.append(g[2])
            out.append(ids)
        tri = Poly_Triangulation(len(nodes), len(out), False, True)
        for i, (p, nv) in enumerate(zip(nodes, normals)):
            tri.SetNode(i + 1, gp_Pnt(*p))
            ln = math.sqrt(nv[0] ** 2 + nv[1] ** 2 + nv[2] ** 2) or 1.0
            tri.SetNormal(i + 1, gp_Dir(nv[0] / ln, nv[1] / ln, nv[2] / ln))
        for i, (a, b, c) in enumerate(out):
            tri.SetTriangle(i + 1, Poly_Triangle(a + 1, b + 1, c + 1))
        face = TopoDS_Face()
        BRep_Builder().MakeFace(face, tri)
        _mesh_cache[key] = bd.Face(face)
    return _mesh_cache[key]


def mesh_bounds(name, T):
    """World bounding box of a placed part, from its vertices."""
    v, _ = _arrays(name)
    lo, hi = [1e9] * 3, [-1e9] * 3
    for i in range(0, len(v), 3):
        p = apply(T, (v[i], v[i + 1], v[i + 2]))
        for k in range(3):
            lo[k] = min(lo[k], p[k])
            hi[k] = max(hi[k], p[k])
    return lo, hi


def part(name, T, label, color):
    """Place V1 part `name` with transform T (improper T uses the mirrored mesh)."""
    R, t = T
    mirror = det(R) < 0
    if mirror:   # fold the reflection into the mesh, keep a proper rotation
        R = [[-R[r][0], R[r][1], R[r][2]] for r in range(3)]
    plane = bd.Plane(origin=tuple(t), x_dir=(R[0][0], R[1][0], R[2][0]), z_dir=(R[0][2], R[1][2], R[2][2]))
    s = mesh(name, mirror).moved(bd.Location(plane))
    s.label = label
    s.color = color
    return s


def tube(length, label, at, axis="Z", color=STEEL, od=None, wall=None):
    r = (od or P["tube_od"]) / 2
    w = wall or P["tube_wall"]
    t = bd.Cylinder(r, length) - bd.Cylinder(r - w, length)
    rot = {"X": (0, 90, 0), "Y": (90, 0, 0), "Z": (0, 0, 0)}[axis]
    t = t.moved(bd.Location(tuple(at), rot))
    t.label = label
    t.color = color
    return t


def box(size, centre, label, color):
    b = bd.Box(*size).moved(bd.Location(tuple(centre)))
    b.label = label
    b.color = color
    return b


def rod(d, length, base, label, color):
    c = bd.Cylinder(d / 2, length, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    c = c.moved(bd.Location(tuple(base)))
    c.label = label
    c.color = color
    return c


A, B = COL["A"], COL["B"]
NEMA = (42.3, 42.3, 40.0)

# ---- measured part geometry (V1 STL coordinates, mm) -----------------------
# Corner Leg Lock: printed upside down; leg bore (100, 123.38), floor 8 thick.
# Corner Bottom: rail U-slot along Zp at (70.65, 104.39), r 12.85, opens +Yp; seat face Yp=80.5;
#   leg screw on (Xp 70.65, Zp 42.85); mating face Yp=117.4; belt slot Xp 43.2-55.8, Yp 101.4-113.2.
# Corner Top: rail U-slot along Zp at (106.75, 100.75), opens to mating face Yp=113.7;
#   bolt pattern 90 degrees to the bottom's; belt slot Xp 79.3-91.4 from Yp 89.2.
# Truck: rail along Zp at (Xp 117.44, Yp 84.07) - top bearings on M8 at Yp 107.77 ride it;
#   gantry saddle along Xp at (Yp 127.78, Zp 62.5); NEMA17 at (Xp 63.24, Zp 26.8), plate top Yp 101.3.
# Truck Clamp: tube along Zc at (62.56, 66.88), opens -Yc, 18 thick (Zc 31.9-49.9).
# Core: leadscrew (100, 79.73); Z rails (64.28 / 135.72, 103.91); X gantry channel along (1,1)
#   at (x-y)/sqrt2 = 49.96, z 56.25; Y gantry along (1,-1) at (x+y)/sqrt2 = 129.45/sqrt2, z 83.75.
#   Core Clamp bolts (60 deg to vertical) put the clamps at stations s = 143.75 / 195.2 (X gantry)
#   and -2.32 / -53.74 (Y gantry).
# Core Clamp: 3 bearings at 120 deg around a tube along Zc at (100, 85.38), mid-plane Zc 11.
# Z Motor: rails (64.27 / 135.73, 145.34), motor (100, 121.16) - same frame as the core, y - 41.43.
# Z Coupler: the Z Motor plate printed upside down (rails at y 54.67).
# Tool Plates: rail cups (64.23 / 135.77, 103.58), clamp arc r 44.4 centred (100, 51.94).
# 55mm mount: spindle along Yp at (43.66, 41.82), back half against the tool plates.
LEG_LOCK_FLOOR = 8.0
U_SAG = 0.15                       # rail (r 12.7) resting in a 12.85 U-slot
RAIL_STACK = 27.5                  # upper - lower rail, = core gantry channel separation
GANTRY_ABOVE_RAIL = 127.78 - 84.07
CORE_GX = (49.96, 56.25)           # X gantry: w=(x-y)/sqrt2, z
CORE_GY = (-129.45 * S2, 83.75)    # Y gantry: w2=-(x+y)/sqrt2, z
LEAD = (100.0, 79.73)
Z_RAILS = ((64.28, 103.91), (135.72, 103.91))
SPINDLE_AXIS = (100.0, 155.55)     # core frame; 51.64 in front of the Z rail line
Z_COUPLER_GAP = 8.0

# ---- base -----------------------------------------------------------------
lx = C["x_table"] / 2 - 26.5
ly = C["y_table"] / 2 - 26.5
leg = C["leg"]
z_ll_top = leg + LEG_LOCK_FLOOR
z_lr = z_ll_top + (104.39 - 80.5) - U_SAG       # Y rails
z_ur = z_lr + RAIL_STACK                          # X rails
z_gx = z_lr + GANTRY_ABOVE_RAIL
z_gy = z_ur + GANTRY_ABOVE_RAIL
z_core0 = z_gx - CORE_GX[1]

corners, bounds = [], {}
for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (1, 1), (-1, 1)]):
    X, Y = sx * lx, sy * ly
    T_cb = frame([(-sx, 0, 0), (0, 0, 1), (0, -sy, 0)], (70.65, 80.5, 42.85), (X, Y, z_ll_top))
    T_ct = frame([(0, -sy, 0), (0, 0, -1), (-sx, 0, 0)], (106.75, 100.75, 42.59), (X, Y, z_ur + U_SAG))
    slider = [(0, 0, 1), (0, 1, 0), (-1, 0, 0)]
    T_lb = compose(T_cb, frame(slider, (72.5, 88.2, 6.9), (49.5, 101.4, 6.0)))
    T_ub = compose(T_ct, frame(slider, (72.5, 65.7, 6.9), (85.35, 89.2, 6.0)))
    m = det(T_cb[0]) < 0
    corners.append(bd.Compound(label=f"Corner {i + 1}", children=[
        part("foot", frame([(1, 0, 0), (0, 1, 0), (0, 0, 1)], (28.35, 107.9, 0), (X, Y, 0)), "Feet", A),
        tube(leg, "Leg", (X, Y, leg / 2)),
        part("leg_lock", frame([(1, 0, 0), (0, -1, 0), (0, 0, -1)], (100, 123.38, 0), (X, Y, z_ll_top)),
             "Corner Leg Lock", B),
        part("corner_bottom", T_cb, "Corner Bottom" + (" Mirrored" if m else ""), B),
        part("corner_top", T_ct, "Corner Top" + (" Mirrored" if m else ""), A),
        part("lower_belt", T_lb, "Lower Belt" + (" Mirrored" if m else ""), A),
        part("upper_belt", T_ub, "Upper Belt" + (" Mirrored" if m else ""), B),
    ]))
    bounds[f"corner{i}"] = [mesh_bounds("corner_bottom", T_cb), mesh_bounds("corner_top", T_ct)]

rails = [tube(C["y_rail"], f"Y rail {'L' if s < 0 else 'R'}", (s * lx, 0, z_lr), "Y") for s in (-1, 1)]
rails += [tube(C["x_rail"], f"X rail {'F' if s < 0 else 'B'}", (0, s * ly, z_ur), "X") for s in (-1, 1)]

# ---- travel: trucks between corners, spindle from the gantry positions --------
# Truck along-rail extent: Zp 0..95 about the gantry saddle at Zp 62.5.
inner_x = -max(max(bb[1][0] for bb in bounds["corner0"]), max(bb[1][0] for bb in bounds["corner3"]))
inner_y = -max(max(bb[1][1] for bb in bounds["corner0"]), max(bb[1][1] for bb in bounds["corner1"]))
xg_lo, xg_hi = -inner_x + 62.5, inner_x - (95 - 62.5)
yg_lo, yg_hi = -inner_y + 62.5, inner_y - (95 - 62.5)

# Spindle axis relative to the gantry tubes (core turned 135 deg, pointing at 0,0).
# world X = -(x+y)/sqrt2 and world Y = (x-y)/sqrt2 in the core frame
dx_lead = CORE_GY[0] + (LEAD[0] + LEAD[1]) * S2       # Y gantry x - leadscrew x
dy_lead = CORE_GX[0] - (LEAD[0] - LEAD[1]) * S2       # X gantry y - leadscrew y
sp = ((SPINDLE_AXIS[0] - LEAD[0]), (SPINDLE_AXIS[1] - LEAD[1]))
sp_world = (-S2 * sp[0] - S2 * sp[1], S2 * sp[0] - S2 * sp[1])   # spindle - leadscrew, world
gx_to_tool = (sp_world[0] - dx_lead, sp_world[1] - dy_lead)       # tool - gantry position

# ---- moving parts: trucks, gantry, core, Z axis - all placed from the tool position ----
d1, w1 = (S2, S2, 0), (S2, -S2, 0)       # X gantry direction / outward normal in core frame
d2, w2 = (S2, -S2, 0), (-S2, -S2, 0)     # Y gantry
zc = (0, 0, 1)
I3 = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
FLIP_X = [(1, 0, 0), (0, -1, 0), (0, 0, -1)]
ROT_Z180 = [(-1, 0, 0), (0, -1, 0), (0, 0, 1)]
MOUNT = [(-1, 0, 0), (0, 0, 1), (0, 1, 0)]
zl = C["z_rail"]
spc = P["spindle"]
# Lowest Z: Z Coupler resting on the core top. Travel = calculator Z work.
zrb_low = z_core0 + 140 + 16 + Z_COUPLER_GAP + 16 - zl


def neg(v):
    return tuple(-a for a in v)


def moving(tool_x, tool_y, zrb):
    """(name, T, label, color, group) for every V1 part that moves, plus primitives."""
    xg, yg = tool_x - gx_to_tool[0], tool_y - gx_to_tool[1]
    T_core = rot_z(135, LEAD, (xg - dx_lead, yg - dy_lead), z_core0)
    rt = zrb + zl
    out, prims = [], []

    def core_clamp(name, d, w, w0, z0, s_, flat_out_plus, label):
        # Clamp Zc runs along the tube; flat side (Zc=0) faces away from the other clamp.
        zdir = neg(d) if flat_out_plus else d
        xdir = neg(zc) if flat_out_plus else zc
        tube_pt = tuple(s_ * d[k] + w0 * w[k] + (z0 if k == 2 else 0) for k in range(3))
        out.append((name, compose(T_core, frame([xdir, w, zdir], (100, 85.38, 11), tube_pt)), label, A, "Core"))

    def zc_frame(cols, local, core_pt_xy, z_world):
        return compose(T_core, frame(cols, local, (*core_pt_xy, z_world - z_core0)))

    # trucks: Truck Clamp on the gantry tube in the saddle, centred over the rail
    for T, mirrored, label in [
        (frame([(0, 1, 0), (0, 0, 1), (1, 0, 0)], (117.44, 84.07, 62.5), (xg, -ly, z_ur)), False, "Truck X front"),
        (frame([(0, -1, 0), (0, 0, 1), (1, 0, 0)], (117.44, 84.07, 62.5), (xg, ly, z_ur)), True, "Truck X back"),
        (frame([(1, 0, 0), (0, 0, 1), (0, 1, 0)], (117.44, 84.07, 62.5), (-lx, yg, z_lr)), True, "Truck Y left"),
        (frame([(-1, 0, 0), (0, 0, 1), (0, 1, 0)], (117.44, 84.07, 62.5), (lx, yg, z_lr)), False, "Truck Y right"),
    ]:
        cx_sign = 1 if mirrored else -1
        out.append(("truck", T, "Truck" + (" Mirrored" if mirrored else ""), A, label))
        out.append(("truck_clamp", compose(T, frame([(0, 0, cx_sign), (0, 1, 0), (1, 0, 0)], (62.56, 66.88, 40.9),
                                                    (117.44, 127.78, 62.5))), "Truck Clamp", B, label))
        prims.append((label, box(NEMA, apply(T, (63.24, 101.3 + NEMA[2] / 2, 26.8)), "Stepper NEMA17", MOTOR)))
    prims.append(("Gantry", tube(C["x_gantry"], "X gantry tube", (0, yg, z_gx), "X")))
    prims.append(("Gantry", tube(C["y_gantry"], "Y gantry tube", (xg, 0, z_gy), "Y")))

    # core and its clamps
    out.append(("core", T_core, "Core", B, "Core"))
    core_clamp("core_clamp", d1, w1, CORE_GX[0], CORE_GX[1], 195.2, True, "Core Clamp")
    core_clamp("core_clamp", d1, w1, CORE_GX[0], CORE_GX[1], 143.75, False, "Core Clamp")
    core_clamp("core_clamp", d2, w2, CORE_GY[0], CORE_GY[1], -2.32, True, "Core Clamp")
    core_clamp("core_clamp_y", d2, w2, CORE_GY[0], CORE_GY[1], -53.74, False, "Core ClampY")
    # Core Z Clamps on the core's front ears, top and bottom (placed by their angled faces; approximate)
    for dz in (0, 112):
        out.append(("core_z_clamp_1", compose(T_core, rot_z(45, (93.1, 98.0), (44.76, 126.21), dz)),
                    "Core Z Clamp 1", A, "Core"))
        out.append(("core_z_clamp_2", compose(T_core, rot_z(135, (89.8, 141.9), (155.24, 126.21), dz)),
                    "Core Z Clamp 2", A, "Core"))

    # Z axis and tool
    for x, y in Z_RAILS:
        prims.append(("Z axis", tube(zl, "Z rail", apply(T_core, (x, y, zrb - z_core0 + zl / 2)))))
        out.append(("nut_trap", zc_frame([(0, 0, 1), (1, 0, 0), (0, 1, 0)], (44.5, 100, 7.45), (x, y), zrb),
                    "Nut Trap", A, "Z axis"))
    out += [
        ("z_motor", zc_frame(I3, (100, 145.34, 16), (100, 103.91), rt), "Z Motor", A, "Z axis"),
        ("z_coupler", zc_frame(FLIP_X, (100, 54.67, 16), (100, 103.91), rt - 32 - Z_COUPLER_GAP), "Z Coupler", A,
         "Z axis"),
        ("lower_tool_plate", zc_frame(ROT_Z180, (100, 51.94, 0), SPINDLE_AXIS, zrb), "Lower Tool Plate", A, "Z axis"),
        ("upper_tool_plate", zc_frame(ROT_Z180, (100, 51.94, 0), SPINDLE_AXIS, zrb + 73), "Upper Tool Plate", A,
         "Z axis"),
        ("spindle_back", zc_frame(MOUNT, (43.66, 0, 41.82), SPINDLE_AXIS, zrb), "55mm Mount (back)", B, "Z axis"),
        ("spindle_front", zc_frame(MOUNT, (43.66, 0, 41.82), SPINDLE_AXIS, zrb), "55mm Mount (front)", B, "Z axis"),
    ]
    lead_len = min(300, zl - 10)
    sp_w = apply(T_core, (*SPINDLE_AXIS, 0))[:2]
    body_z = zrb - spc["below_clamp"]
    tip = body_z - spc["nut_len"] - spc["bit_stickout"]
    prims += [
        ("Z axis", box(NEMA, apply(T_core, (*LEAD, rt + NEMA[2] / 2 - z_core0)), "Stepper NEMA17 (Z)", MOTOR)),
        ("Z axis", rod(8, lead_len, apply(T_core, (*LEAD, rt - 10 - lead_len - z_core0)), "Leadscrew T8", STEEL)),
        ("Z axis", rod(spc["d"], spc["body_len"], (*sp_w, body_z), "Spindle 55mm", SPINDLE)),
        ("Z axis", rod(32, spc["nut_len"], (*sp_w, body_z - spc["nut_len"]), "ER collet nut", STEEL)),
        ("Z axis", rod(3.175, spc["bit_stickout"], (*sp_w, tip), "Bit 1/8in", STEEL)),
    ]
    return out, prims, (xg, yg), tip


# ---- work area: where the tool can go before anything hits ------------------------
# Trucks stop at the corners; the core, Z axis and mount stop at the opposite trucks
# (truck inner face: 158.3 - 117.44 = 40.86 inboard of the rail). Bounding boxes, so
# this is slightly conservative.
truck_in_x, truck_in_y = lx - 40.86, ly - 40.86
probe, _, _, _ = moving(0.0, 0.0, zrb_low)
rel_lo, rel_hi = [1e9] * 3, [-1e9] * 3
for name, T, label, color, group in probe:
    if group in ("Core", "Z axis"):
        lo, hi = mesh_bounds(name, T)
        rel_lo = [min(a, b) for a, b in zip(rel_lo, lo)]
        rel_hi = [max(a, b) for a, b in zip(rel_hi, hi)]
rel_lo[0] = min(rel_lo[0], -spc["d"] / 2)
tx_lo = max(xg_lo + gx_to_tool[0], -truck_in_x - rel_lo[0])
tx_hi = min(xg_hi + gx_to_tool[0], truck_in_x - rel_hi[0])
ty_lo = max(yg_lo + gx_to_tool[1], -truck_in_y - rel_lo[1])
ty_hi = min(yg_hi + gx_to_tool[1], truck_in_y - rel_hi[1])
wcx, wcy = (tx_lo + tx_hi) / 2, (ty_lo + ty_hi) / 2
tool_x = wcx + (P["pose"]["x"] - 0.5) * C["x_work"]
tool_y = wcy + (P["pose"]["y"] - 0.5) * C["y_work"]
zrb = zrb_low + P["pose"]["z"] * C["z_work"]
placed, prims, (xg, yg), tip = moving(tool_x, tool_y, zrb)

groups = {}
for name, T, label, color, group in placed:
    groups.setdefault(group, []).append(part(name, T, label, color))
for group, shape in prims:
    groups.setdefault(group, []).append(shape)
truck_names = ["Truck X front", "Truck X back", "Truck Y left", "Truck Y right"]
trucks = [bd.Compound(label=n, children=groups[n]) for n in truck_names]
gantry = groups["Gantry"]
core_parts = groups["Core"]
z_parts = groups["Z axis"]

# ---- table and work area ---------------------------------------------------------
table = box((max(P["footprint_x"], 1000), max(P["footprint_y"], 1000), 18), (0, 0, -9), "Table top", TABLE)
work = box((C["x_work"], C["y_work"], 0.5), (wcx, wcy, 0.25), "Work area (V1 calculator)", WORK)

if P.get("debug_report"):
    raise RuntimeError(repr({
        "truck_travel_x": round(xg_hi - xg_lo, 1), "truck_travel_y": round(yg_hi - yg_lo, 1),
        "tool_range_x": (round(tx_lo, 1), round(tx_hi, 1), round(tx_hi - tx_lo, 1)),
        "tool_range_y": (round(ty_lo, 1), round(ty_hi, 1), round(ty_hi - ty_lo, 1)),
        "rel_core_group": ([round(v, 1) for v in rel_lo], [round(v, 1) for v in rel_hi]),
        "work_centre": (round(wcx, 1), round(wcy, 1)), "tool": (round(tool_x, 1), round(tool_y, 1)),
        "z": {"lower_rail": round(z_lr, 2), "upper_rail": round(z_ur, 2), "x_gantry": round(z_gx, 2),
              "y_gantry": round(z_gy, 2), "core_bottom": round(z_core0, 2), "z_rail_bottom_low": round(zrb_low, 2),
              "tip_low": round(zrb_low - spc["below_clamp"] - spc["nut_len"] - spc["bit_stickout"], 2)},
    }))

model = bd.Compound(label="MPCNC Primo J", children=[
    table, work,
    bd.Compound(label="Base", children=[bd.Compound(label="Corners", children=corners),
                                        bd.Compound(label="Rails", children=rails)]),
    bd.Compound(label="Gantry", children=[*trucks, *gantry]),
    bd.Compound(label="Core", children=core_parts),
    bd.Compound(label="Z axis", children=z_parts),
])
