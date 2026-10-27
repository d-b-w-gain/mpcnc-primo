"""Pure-Python sizing for the MPCNC Primo: V1's cut calculator. Runs without build123d,
so `python3 primo_calc.py` prints the cut list locally."""
import json
from pathlib import Path


def load_params():
    return json.loads((Path(__file__).parent / "params.json").read_text())


def cut_list(P):
    """V1 calculator (Primo), solved backwards from the overall footprint."""
    base = P["calculator"]["base"]
    tool = P["calculator"]["tools"][P["tool"]]
    xy, zt = tool["xy"], tool["z"]
    xrail = P["footprint_x"] - base["bound_minus_rail"]
    yrail = P["footprint_y"] - base["bound_minus_rail"]
    xwork = xrail - (base["xrail"] + xy)
    ywork = yrail - (base["yrail"] + xy)
    zwork = P["z_work"]
    c = {
        "x_work": xwork,
        "y_work": ywork,
        "z_work": zwork,
        "x_rail": xrail,
        "y_rail": yrail,
        "x_gantry": xwork + base["xgantry"] + xy,
        "y_gantry": ywork + base["ygantry"] + xy,
        "z_rail": zwork + base["zrail"] + zt,
        "leg": zwork + base["zleg"] + zt,
        "x_table": xrail + base["table_minus_rail"],
        "y_table": yrail + base["table_minus_rail"],
        "x_belt": xrail + base["belt_minus_rail"],
        "y_belt": yrail + base["belt_minus_rail"],
    }
    c["tube_total"] = (2 * c["x_rail"] + c["x_gantry"] + 2 * c["y_rail"] + c["y_gantry"]
                       + 2 * c["z_rail"] + 4 * c["leg"] + 12 * P["kerf"])
    c["belt_total"] = 2 * c["x_belt"] + 2 * c["y_belt"]
    if min(xwork, ywork) <= 0 or c["leg"] <= 0:
        raise ValueError(f"footprint too small for a Primo: {c}")
    return c


if __name__ == "__main__":
    P = load_params()
    c = cut_list(P)
    print(f"MPCNC Primo J, {P['footprint_x']} x {P['footprint_y']} footprint, tool {P['tool']}")
    print(f"work area     {c['x_work']:.1f} x {c['y_work']:.1f} x {c['z_work']:.1f} mm")
    for k, q in [("x_rail", 2), ("y_rail", 2), ("x_gantry", 1), ("y_gantry", 1), ("z_rail", 2), ("leg", 4)]:
        print(f"  {q} x {k:9s} {c[k]:7.1f} mm")
    print(f"tube total    {c['tube_total']:.0f} mm (3 mm kerf)")
    print(f"belt          2 x {c['x_belt']:.0f} + 2 x {c['y_belt']:.0f} = {c['belt_total']:.0f} mm of 10 mm GT2")
    print(f"table (feet)  {c['x_table']:.0f} x {c['y_table']:.0f} mm")
