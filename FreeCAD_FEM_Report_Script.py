# -*- coding: utf-8 -*-
"""
FEM ENGINEERING REPORT v1 – FreeCAD / FEM / CalculiX
========================================================
© Ing. Marek Petschenka; https://print-lab.netlify.app/
========================================================

This version is intended for the workflow in which the user:

    1. completes the CalculiX calculation,
    2. SELECTS a specific CCX_Results object in the Tree View,
    3. runs this script.

The script does NOT replace the FEM solver. It reads already calculated results.

Output:
    PAGE 1  – technical text report
    PAGE 2  – three graphical results:
               CCX Result - Displacement magnitude (ISO view)
               CCX Result - von Mises Stress (ISO view)
               CCX Result - Maximum principal stress (ISO view)

PDF:
    - two SVG pages are assembled as the technical report,
    - the final PDF is created as a multi-page A4 PDF using Qt/QPdfWriter.
    - TechDraw pages are not created to avoid conflicts with an active task panel.

Important:
    - The script uses the EXACTLY selected CCX_Results object.
    - It does not automatically choose another result based on an internal score.
    - Graphics are generated from result.Mesh + result.NodeNumbers + the corresponding
      result field, analogous to FreeCAD FEM Result Show.

Actual FreeCAD FEM API use:
    DisplacementLengths
    DisplacementVectors
    vonMises
    PrincipalMax
    PrincipalMed
    PrincipalMin
    MaxShear

Official FEM Result Show:
    Uabs        -> DisplacementLengths
    Sabs        -> vonMises
    MaxPrin     -> PrincipalMax

Usage:
    - Open the completed FEM model.
    - Select the required CCX_Resultsxxx in the Tree View.
    - Open View -> Panels -> Python console.
    - Paste the entire script.
    - Before every run, a folder-selection dialog asks where the PDF and all generated images/SVG files shall be stored.

Configuration is at the top of the file.
"""

import os
import re
import base64
import datetime
import traceback
import math

import FreeCAD as App
import FreeCADGui as Gui


# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    # Report identification
    "COMPANY": "YOUR COMPANY",
    "PROJECT": "",                         # empty = document label
    "AUTHOR": os.environ.get(
        "USERNAME",
        os.environ.get("USER", "Author")
    ),
    "REPORT_TITLE": "TECHNICAL REPORT – FEM ANALYSIS",
    "REPORT_SUBTITLE": "CalculiX / CCX Result – automated post-processing",

    # Output
    "OUTPUT_DIR": os.path.join(
        os.path.expanduser("~"),
        "Desktop"
    ),
    "OUTPUT_FILE": "",                     # empty = automatic name
    # Before EVERY report run, a folder-selection dialog appears.
    "ASK_OUTPUT_DIR": True,

    # Displacement design criterion; None = informational result only
    "MAX_ALLOWED_DISPLACEMENT_MM": None,

    # Graphical result settings
    "IMAGE_WIDTH": 1800,
    "IMAGE_HEIGHT": 1000,

    # Displacement scale factor for visualization.
    # FreeCAD Result Show standardly uses a factor for visualization.
    "DISPLACEMENT_SCALE": 5.0,

    # Keep the selected CCX Result displayed graphically as Uabs at the end.
    "FINAL_RESULT_MODE": "Uabs",

    # Display FEM constraint symbols in the report if visible in the scene.
    "SHOW_CONSTRAINT_SYMBOLS": True,

    # Keep TechDraw pages in the document.
    "KEEP_TECHDRAW_PAGES": False,

    # Global font downscaling for the A4 report.
    "FONT_SCALE": 0.76,
}


# ============================================================================
# LOG / UTILITY
# ============================================================================

def log(msg):
    try:
        App.Console.PrintMessage(str(msg) + "\n")
    except Exception:
        print(msg)


def warn(msg):
    try:
        App.Console.PrintWarning(str(msg) + "\n")
    except Exception:
        print("WARNING:", msg)


def err(msg):
    try:
        App.Console.PrintError(str(msg) + "\n")
    except Exception:
        print("ERROR:", msg)


def safe_str(value, default=""):
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def esc(value):
    s = safe_str(value)
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def compact_text(value, max_len=90):
    s = safe_str(value).replace("\n", " ").strip()
    if len(s) <= max_len:
        return s
    return s[:max_len - 3] + "..."


def file_safe_name(name):
    s = safe_str(name, "FEM_Report")
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    s = re.sub(r"\s+", "_", s)
    return s[:120]


def finite(v):
    try:
        return math.isfinite(float(v))
    except Exception:
        return False


def fmt(value, decimals=3, unit="", default="not available"):
    if value is None:
        return default
    try:
        x = float(value)
        s = f"{x:.{decimals}f}"
        return f"{s} {unit}" if unit else s
    except Exception:
        return safe_str(value, default)


def fmt_int(value, default="not available"):
    if value is None:
        return default
    try:
        return f"{int(value):,}".replace(",", " ")
    except Exception:
        return safe_str(value, default)


def get_properties(obj):
    try:
        return list(obj.PropertiesList)
    except Exception:
        return []


def get_property(obj, names, default=None):
    if obj is None:
        return default

    wanted = {str(n).lower() for n in names}

    for pname in get_properties(obj):
        if pname.lower() in wanted:
            try:
                return getattr(obj, pname)
            except Exception:
                pass

    for name in names:
        try:
            if hasattr(obj, name):
                return getattr(obj, name)
        except Exception:
            pass

    return default


def object_type(obj):
    return safe_str(getattr(obj, "TypeId", "")).lower()


def object_label(obj):
    if obj is None:
        return "-"
    return safe_str(
        getattr(obj, "Label", getattr(obj, "Name", "-")),
        "-"
    )


def to_float(value):
    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        pass

    try:
        m = re.search(
            r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?",
            safe_str(value)
        )
        return float(m.group(0)) if m else None
    except Exception:
        return None


def quantity_to_float(value, target_unit=None):
    if value is None:
        return None

    if target_unit:
        try:
            q = App.Units.Quantity(safe_str(value))
            return float(q.getValueAs(target_unit))
        except Exception:
            pass

    return to_float(value)


# ============================================================================
# ANALYSIS + SELECTED CCX RESULT
# ============================================================================

def find_analysis(doc):
    for obj in doc.Objects:
        if "femanalysis" in object_type(obj):
            return obj

    for obj in doc.Objects:
        if safe_str(getattr(obj, "Name", "")).lower() == "analysis":
            return obj

    for obj in doc.Objects:
        text = (object_type(obj) + " " + object_label(obj)).lower()
        if "analysis" in text and "fem" in text:
            return obj

    return None


def analysis_members(analysis):
    result = []
    if analysis is None:
        return result

    for prop in ("Group", "Member"):
        try:
            values = getattr(analysis, prop)
            if values:
                for obj in values:
                    if obj not in result:
                        result.append(obj)
        except Exception:
            pass

    return result


def is_mechanical_result(obj):
    if obj is None:
        return False

    t = object_type(obj)

    if "femresult" in t or "resultmechanical" in t:
        return True

    for prop in (
        "DisplacementVectors",
        "DisplacementLengths",
        "vonMises",
        "PrincipalMax"
    ):
        try:
            if hasattr(obj, prop):
                return True
        except Exception:
            pass

    return False


def _is_ccx_by_name(obj):
    """Loose identification of CCX results by Name/Label.

    Some FreeCAD versions expose CalculiX results as Python objects
    with a different TypeId, so we must not rely solely on isDerivedFrom/TypeId.
    """
    if obj is None:
        return False

    name = safe_str(getattr(obj, "Name", ""))
    label = object_label(obj)
    text = (name + " " + label).lower()

    # Result, not result mesh CCX_Resultsxxx_Mesh
    if "ccx_results" in text and "_mesh" not in text:
        return True
    if "ccxresult" in text and "mesh" not in text:
        return True
    if "calculix" in text and ("result" in text or "results" in text):
        return True
    return False


def is_ccx_result(obj):
    """Robust identification of the actual CCX Result object."""
    if obj is None:
        return False

    if _is_ccx_by_name(obj):
        return True

    # Standard FEM mechanical result as a fallback.
    return is_mechanical_result(obj)


def _selected_gui_objects():
    """Returns unique objects from both standard and Extended GUI selections."""
    result = []
    try:
        for obj in Gui.Selection.getSelection():
            if obj not in result:
                result.append(obj)
    except Exception:
        pass

    try:
        for item in Gui.Selection.getSelectionEx():
            obj = getattr(item, "Object", None)
            if obj is not None and obj not in result:
                result.append(obj)
    except Exception:
        pass

    return result


def find_selected_ccx_result(doc):
    """Finds the currently selected CCX Result.

    Order:
      1) GUI selection by Name/Label,
      2) GUI selection as standard FEM result,
      3) single visible CCX Result,
      4) single CCX Result in the document.

    The last two variants are compatibility fallbacks only, and a log warning
    is issued that GUI selection was not available.
    """
    selection = _selected_gui_objects()

    # 1. Exactly CCX by Name/Label — FIRST.
    for obj in selection:
        if _is_ccx_by_name(obj):
            return obj

    # 2. Standard FEM result as fallback.
    for obj in selection:
        if is_mechanical_result(obj):
            return obj

    # 3. Single visible CCX result.
    visible_ccx = []
    for obj in doc.Objects:
        if _is_ccx_by_name(obj):
            try:
                if bool(obj.ViewObject.Visibility):
                    visible_ccx.append(obj)
            except Exception:
                pass

    if len(visible_ccx) == 1:
        warn(
            "GUI selection was not available; the only visible CCX Result was used: "
            + object_label(visible_ccx[0])
        )
        return visible_ccx[0]

    # 4. Single CCX result in the document.
    all_ccx = [obj for obj in doc.Objects if _is_ccx_by_name(obj)]
    if len(all_ccx) == 1:
        warn(
            "GUI selection was not available; the only CCX Result in the document was used: "
            + object_label(all_ccx[0])
        )
        return all_ccx[0]

    candidates = [object_label(o) for o in all_ccx]
    raise RuntimeError(
        "Unable to uniquely determine the CCX Result from the GUI selection.\n"
        "Select a specific CCX_Resultsxxx in the Tree View and run the report again.\n"
        + ("Found results: " + ", ".join(candidates) if candidates else "No CCX Result was found in the document.")
    )


# ============================================================================
# RESULT DATA
# ============================================================================

def ensure_result_arrays(result):
    """Computes standard result fields if available."""
    try:
        from femresult import resulttools
    except Exception as exc:
        warn(f"Unable to import femresult.resulttools: {exc}")
        return

    # Uabs
    try:
        if hasattr(result, "DisplacementLengths"):
            vals = getattr(result, "DisplacementLengths")
            if vals is None or len(vals) == 0:
                resulttools.add_disp_apps(result)
    except Exception as exc:
        warn(f"Unable to compute DisplacementLengths: {exc}")

    # von Mises
    try:
        if hasattr(result, "vonMises"):
            vals = getattr(result, "vonMises")
            if vals is None or len(vals) == 0:
                resulttools.add_von_mises(result)
    except Exception as exc:
        warn(f"Unable to compute vonMises: {exc}")

    # Principal stresses
    try:
        has_principal = False
        try:
            has_principal = len(getattr(result, "PrincipalMax")) > 0
        except Exception:
            has_principal = False

        if not has_principal:
            resulttools.add_principal_stress_std(result)
    except Exception as exc:
        warn(f"Unable to compute PrincipalMax/PrincipalMin: {exc}")

    try:
        result.Document.recompute()
    except Exception:
        pass


def array_stats(result, property_name):
    try:
        values = list(getattr(result, property_name))
    except Exception:
        return None, None

    vals = []
    for v in values:
        x = to_float(v)
        if x is not None and finite(x):
            vals.append(x)

    if not vals:
        return None, None

    return min(vals), max(vals)


def resulttools_stats(result, result_type):
    try:
        from femresult import resulttools
        mn, mx = resulttools.get_stats(result, result_type)
        return float(mn), float(mx)
    except Exception:
        return None, None


def stress_stats(result, prop_name, result_type):
    mn, mx = resulttools_stats(result, result_type)
    if mn is not None and mx is not None:
        # FreeCAD Result Show uses MPa for stress results.
        # Convert to MPa only if data looks like Pascals.
        if abs(mx) >= 1.0e6:
            return mn / 1.0e6, mx / 1.0e6
        return mn, mx

    mn, mx = array_stats(result, prop_name)
    if mn is not None and mx is not None and abs(mx) >= 1.0e6:
        return mn / 1.0e6, mx / 1.0e6

    return mn, mx


def displacement_stats(result):
    mn, mx = resulttools_stats(result, "Uabs")
    if mn is not None and mx is not None:
        # FreeCAD FEM Result Show returns displacement in mm.
        # Conservative fallback for data in meters.
        if abs(mx) < 1.0e-3:
            return mn * 1000.0, mx * 1000.0
        return mn, mx

    mn, mx = array_stats(result, "DisplacementLengths")
    if mn is not None and mx is not None:
        if abs(mx) < 1.0e-3:
            return mn * 1000.0, mx * 1000.0
        return mn, mx

    # Vector fallback
    try:
        vecs = list(getattr(result, "DisplacementVectors"))
        mags = []
        for v in vecs:
            x = float(getattr(v, "x", 0.0))
            y = float(getattr(v, "y", 0.0))
            z = float(getattr(v, "z", 0.0))
            mags.append(math.sqrt(x*x + y*y + z*z))

        if mags:
            mn, mx = min(mags), max(mags)
            if abs(mx) < 1.0e-3:
                return mn * 1000.0, mx * 1000.0
            return mn, mx
    except Exception:
        pass

    return None, None


def get_all_result_stats(result):
    ensure_result_arrays(result)

    disp_min, disp_max = displacement_stats(result)
    vm_min, vm_max = stress_stats(result, "vonMises", "Sabs")
    pmax_min, pmax_max = stress_stats(result, "PrincipalMax", "MaxPrin")
    pmin_min, pmin_max = stress_stats(result, "PrincipalMin", "MinPrin")

    return {
        "disp_min": disp_min,
        "disp_max": disp_max,
        "vm_min": vm_min,
        "vm_max": vm_max,
        "pmax_min": pmax_min,
        "pmax_max": pmax_max,
        "pmin_min": pmin_min,
        "pmin_max": pmin_max,
    }


# ============================================================================
# RESULT MESH / MESH STATISTICS
# ============================================================================

def get_result_mesh(result):
    """Returns the FEM result mesh directly from the selected CCX Result."""
    if result is None:
        return None

    try:
        mesh = getattr(result, "Mesh", None)
        if mesh is not None:
            return mesh
    except Exception:
        pass

    # Fallback: search for an object with FemMesh whose name matches Result mesh.
    try:
        doc = result.Document
        prefix = safe_str(getattr(result, "Name", ""))
        candidates = []
        for obj in doc.Objects:
            if getattr(obj, "FemMesh", None) is None:
                continue
            name = safe_str(getattr(obj, "Name", ""))
            label = object_label(obj)
            if prefix and prefix in name:
                candidates.append(obj)
            elif "result" in (name + " " + label).lower() and "mesh" in (name + " " + label).lower():
                candidates.append(obj)
        if len(candidates) == 1:
            return candidates[0]
    except Exception:
        pass

    return None


def get_mesh_backend(mesh_obj):
    """Returns the internal FemMesh object."""
    if mesh_obj is None:
        return None

    try:
        fm = getattr(mesh_obj, "FemMesh", None)
        if fm is not None:
            return fm
    except Exception:
        pass

    # Some FreeCAD versions expose methods directly.
    if any(hasattr(mesh_obj, name) for name in ("getNodeCount", "getNodeCount")):
        return mesh_obj

    return None


def call_count(obj, names):
    for name in names:
        try:
            fn = getattr(obj, name)
            return int(fn())
        except Exception:
            pass
    return 0


def _mesh_collection(obj, name):
    """Safely gets Nodes/Volumes/Faces/Edges as dict/list."""
    try:
        value = getattr(obj, name)
        if value is None:
            return {}
        return value
    except Exception:
        return {}


def _collection_items(collection):
    if collection is None:
        return []

    try:
        if hasattr(collection, "items"):
            return list(collection.items())
    except Exception:
        pass

    try:
        return list(enumerate(collection))
    except Exception:
        return []


def _element_type_from_node_count(n_nodes, dimension):
    """Mapping of FreeCAD FEM elements to CalculiX types."""
    if dimension == "volume":
        mapping = {
            4:  ("C3D4",  "tetra4 – linear tetrahedron"),
            10: ("C3D10", "tetra10 – quadratic tetrahedron"),
            8:  ("C3D8",  "hexa8 – linear hexahedron"),
            20: ("C3D20", "hexa20 – quadratic hexahedron"),
            6:  ("C3D6",  "penta6 – linear wedge"),
            15: ("C3D15", "penta15 – quadratic wedge"),
            5:  ("C3D5",  "pyra5 – linear pyramid"),
            13: ("C3D13", "pyra13 – quadratic pyramid"),
        }
    elif dimension == "face":
        mapping = {
            3: ("S3", "tria3 – triangle"),
            6: ("S6", "tria6 – quadratic triangle"),
            4: ("S4", "quad4 – quadrilateral"),
            8: ("S8", "quad8 – quadratic quadrilateral"),
        }
    else:
        mapping = {
            2: ("B31", "seg2 – linear element"),
            3: ("B32", "seg3 – quadratic element"),
        }

    return mapping.get(
        int(n_nodes),
        ("UNKNOWN", f"{int(n_nodes)} nodes")
    )


def _get_mesh_ids(fm, kind):
    """Returns FEM element IDs via compatible API."""
    method_names = {
        "volume": ("getVolumes",),
        "face": ("getFaces",),
        "edge": ("getEdges",),
    }

    for name in method_names.get(kind, ()):
        try:
            value = getattr(fm, name)()
            return list(value)
        except Exception:
            pass

    prop_names = {
        "volume": ("Volumes",),
        "face": ("Faces",),
        "edge": ("Edges",),
    }
    for name in prop_names.get(kind, ()):
        try:
            value = getattr(fm, name)
            return list(value)
        except Exception:
            pass

    return []


def _element_nodes(fm, element_id):
    try:
        return list(fm.getElementNodes(element_id))
    except Exception:
        return []


def _count_element_types(fm, ids, dimension):
    """Determines actual element type from connectivity node counts."""
    counts = {}
    for element_id in ids:
        nodes = _element_nodes(fm, element_id)
        if not nodes:
            continue
        ccx, description = _element_type_from_node_count(len(nodes), dimension)
        key = (ccx, description)
        counts[key] = counts.get(key, 0) + 1
    return counts


def mesh_statistics(mesh_obj):
    """Robust statistics of the FEM result mesh.

    Uses actual FemMesh API:
        getNodeCount()
        getVolumes()/getFaces()/getEdges()
        getElementNodes()

    This avoids dependency on whether a specific build exposes
    Python properties Nodes/Volumes/Faces/Edges.
    """
    fm = get_mesh_backend(mesh_obj)
    if fm is None:
        return None

    # Number of nodes
    nodes = call_count(fm, ("getNodeCount", "getNodesCount"))

    # Element IDs by dimension
    volume_ids = _get_mesh_ids(fm, "volume")
    face_ids = _get_mesh_ids(fm, "face")
    edge_ids = _get_mesh_ids(fm, "edge")

    volumes = len(volume_ids)
    faces = len(face_ids)
    edges = len(edge_ids)

    if volumes > 0:
        elements = volumes
        kind = "volumetric mesh (3D)"
        type_counts = _count_element_types(fm, volume_ids, "volume")
    elif faces > 0:
        elements = faces
        kind = "surface mesh (2D)"
        type_counts = _count_element_types(fm, face_ids, "face")
    elif edges > 0:
        elements = edges
        kind = "line mesh (1D)"
        type_counts = _count_element_types(fm, edge_ids, "edge")
    else:
        elements = 0
        kind = "not available"
        type_counts = {}

    if type_counts:
        ordered = sorted(type_counts.items(), key=lambda kv: kv[1], reverse=True)
        (main_ccx, main_desc), main_count = ordered[0]
        type_text = main_ccx
        description_text = main_desc
        distribution = ", ".join(
            f"{ccx} × {count}" for (ccx, _), count in ordered[:8]
        )
    else:
        type_text = "not available"
        description_text = "element type could not be identified from connectivity"
        distribution = "not available"

    # Some CalculiX result meshes report zero through getNodeCount() even
    # though the result object contains the complete node list. Use the
    # result node list as a reliable fallback in that case.
    if nodes <= 0 and elements > 0:
        try:
            node_ids = set()
            source_ids = volume_ids if volumes > 0 else (face_ids if faces > 0 else edge_ids)
            for element_id in source_ids:
                node_ids.update(_element_nodes(fm, element_id))
            if node_ids:
                nodes = len(node_ids)
        except Exception:
            pass

    if nodes <= 0 and elements <= 0:
        return None

    return {
        "nodes": nodes,
        "result_nodes": None,
        "elements": elements,
        "edges": edges,
        "faces": faces,
        "volumes": volumes,
        "kind": kind,
        "element_type": type_text,
        "element_description": description_text,
        "distribution": distribution,
        "volume_types": type_counts if volumes > 0 else {},
        "face_types": type_counts if faces > 0 else {},
        "edge_types": type_counts if edges > 0 else {},
        "mesh_label": object_label(mesh_obj),
    }


def mesh_statistics_with_result(mesh_obj, result):
    info = mesh_statistics(mesh_obj)
    if info is None:
        return None

    try:
        result_nodes = len(list(getattr(result, "NodeNumbers")))
    except Exception:
        result_nodes = None

    info["result_nodes"] = result_nodes

    # In some FreeCAD/CalculiX combinations the result mesh backend returns
    # zero for getNodeCount(), while NodeNumbers is populated correctly.
    # Use the result-node count as the FEM-node count fallback.
    if (info.get("nodes") or 0) <= 0 and result_nodes:
        info["nodes"] = result_nodes

    return info


# ============================================================================
# MATERIAL
# ============================================================================

def material_dict(obj):
    try:
        m = getattr(obj, "Material", None)
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def material_lookup(mat, names):
    wanted = {str(n).lower() for n in names}
    for k, v in mat.items():
        if str(k).lower() in wanted:
            return v
    return None


def find_material(doc, analysis=None):
    candidates = []

    if analysis is not None:
        candidates.extend(analysis_members(analysis))

    for obj in doc.Objects:
        if obj not in candidates:
            candidates.append(obj)

    possible = []
    for obj in candidates:
        t = object_type(obj)
        if "material" in t or hasattr(obj, "Material"):
            possible.append(obj)

    selected = None
    for obj in possible:
        mat = material_dict(obj)
        if material_lookup(mat, ("YoungsModulus", "YoungModulus")) is not None:
            selected = obj
            break

    if selected is None and possible:
        selected = possible[0]

    if selected is None:
        return None

    mat = material_dict(selected)

    name = material_lookup(mat, (
        "Name",
        "MaterialName",
        "CardName"
    ))

    if not name:
        name = get_property(
            selected,
            ("CardName", "MaterialName")
        )

    if not name:
        name = object_label(selected)

    E_raw = material_lookup(
        mat,
        ("YoungsModulus", "YoungModulus")
    )
    if E_raw is None:
        E_raw = get_property(
            selected,
            ("YoungsModulus", "YoungModulus")
        )
    E = quantity_to_float(E_raw, "MPa")

    nu_raw = material_lookup(
        mat,
        ("PoissonRatio", "Poisson")
    )
    if nu_raw is None:
        nu_raw = get_property(
            selected,
            ("PoissonRatio", "Poisson")
        )
    nu = to_float(nu_raw)

    rho_raw = material_lookup(
        mat,
        ("Density", "rho")
    )
    if rho_raw is None:
        rho_raw = get_property(selected, ("Density",))
    rho = quantity_to_float(rho_raw, "kg/m^3")

    Re_raw = material_lookup(
        mat,
        (
            "YieldStrength",
            "YieldStress",
            "Yield",
            "TensileYieldStrength"
        )
    )
    if Re_raw is None:
        Re_raw = get_property(
            selected,
            ("YieldStrength", "YieldStress", "Yield")
        )
    Re = quantity_to_float(Re_raw, "MPa")

    return {
        "object": selected,
        "name": safe_str(name, "Unnamed material"),
        "E_MPa": E,
        "nu": nu,
        "rho": rho,
        "yield_MPa": Re,
    }


# ============================================================================
# BOUNDARY CONDITIONS
# ============================================================================

def find_constraints(analysis):
    rows = []
    if analysis is None:
        return rows

    for obj in analysis_members(analysis):
        t = object_type(obj)
        label = object_label(obj).lower()

        if "constraint" in t or "constraint" in label:
            rows.append(obj)

    return rows


def constraint_type(obj):
    text = (
        object_type(obj)
        + " "
        + object_label(obj)
    ).lower()

    mapping = [
        (("fixed",), "Fixed support"),
        (("force",), "Force"),
        (("pressure",), "Pressure"),
        (("moment", "torque"), "Moment"),
        (("displacement",), "Prescribed displacement"),
        (("rotation",), "Prescribed rotation"),
        (("gravity",), "Gravity"),
        (("temperature",), "Temperature"),
        (("heatflux",), "Heat flux"),
        (("spring",), "Spring"),
        (("contact",), "Contact"),
        (("plane",), "Plane constraint"),
    ]

    for keys, name in mapping:
        if any(k in text for k in keys):
            return name

    return "FEM boundary condition"


def format_references(obj):
    refs = get_property(obj, ("References",), [])
    if not refs:
        return "-"

    out = []
    try:
        for ref in refs:
            try:
                base, sub = ref
                out.append(f"{object_label(base)}:{sub}")
            except Exception:
                out.append(compact_text(ref, 60))
    except Exception:
        return compact_text(refs, 100)

    return "; ".join(out) if out else "-"


def property_string(obj, names):
    value = get_property(obj, names, None)
    if value is None:
        return None

    s = compact_text(value, 60)
    return None if s in ("[]", "()", "{}") else s


def format_constraint_parameters(obj):
    t = object_type(obj)

    if "fixed" in t:
        return "Ux = Uy = Uz = 0"

    chunks = []

    checks = [
        (("Force", "ForceValue", "Magnitude"), "force"),
        (("Pressure",), "pressure"),
        (("Moment", "Torque"), "moment"),
        (("DisplacementX", "xDisplacement"), "Ux"),
        (("DisplacementY", "yDisplacement"), "Uy"),
        (("DisplacementZ", "zDisplacement"), "Uz"),
        (("Temperature",), "T"),
        (("HeatFlux",), "q"),
    ]

    for names, label in checks:
        s = property_string(obj, names)
        if s:
            chunks.append(f"{label}={s}")

    if not chunks:
        keys = (
            "Direction",
            "Reversed",
            "Value",
            "X",
            "Y",
            "Z",
            "Distance",
            "ConstraintTypee"
        )

        for pname in get_properties(obj):
            if any(k.lower() in pname.lower() for k in keys):
                try:
                    value = getattr(obj, pname)
                    s = compact_text(value, 45)
                    if s not in ("[]", "()", "None"):
                        chunks.append(f"{pname}={s}")
                except Exception:
                    pass

            if len(chunks) >= 4:
                break

    return "; ".join(chunks) if chunks else "see geometric reference"


def constraint_data(constraints):
    result = []

    for obj in constraints:
        result.append({
            "type": constraint_type(obj),
            "name": object_label(obj),
            "refs": format_references(obj),
            "params": format_constraint_parameters(obj),
        })

    return result


# ============================================================================
# POST PIPELINE INFO
# ============================================================================

def find_post_pipeline(doc, analysis=None):
    candidates = []

    if analysis is not None:
        candidates.extend(analysis_members(analysis))

    for obj in doc.Objects:
        if obj not in candidates:
            candidates.append(obj)

    for obj in candidates:
        t = object_type(obj)
        if "fempostpipeline" in t or "postpipeline" in t:
            return obj

    return None


# ============================================================================
# GRAPHICS: SELECTED CCX RESULT ITSELF
# ============================================================================

def _is_visual_fem_object(obj):
    t = object_type(obj)
    label = object_label(obj).lower()
    keys = (
        "constraint", "femconstraint", "force", "fixed", "pressure",
        "moment", "gravity", "temperature", "heatflux",
    )
    return any(k in t or k in label for k in keys)


def set_result_scalar_display(result, scalar_name):
    """Sets color mapping directly on the selected CCX Result mesh."""
    mesh = get_result_mesh(result)
    if mesh is None:
        raise RuntimeError("The selected CCX Result does not have an available result.Mesh.")

    ensure_result_arrays(result)

    field_map = {
        "Uabs": ("DisplacementLengths", "mm", "Displacement magnitude"),
        "Sabs": ("vonMises", "MPa", "von Mises stress"),
        "MaxPrin": ("PrincipalMax", "MPa", "Maximum principal stress"),
    }
    if scalar_name not in field_map:
        raise ValueError(f"Unknown result mode: {scalar_name}")

    prop_name, unit, title = field_map[scalar_name]

    try:
        values = list(getattr(result, prop_name))
    except Exception as exc:
        raise RuntimeError(f"Result field {prop_name} is not available: {exc}")

    if not values:
        raise RuntimeError(f"Result field {prop_name} is empty.")

    try:
        node_numbers = list(getattr(result, "NodeNumbers"))
    except Exception as exc:
        raise RuntimeError(f"CCX Result does not have NodeNumbers: {exc}")

    if not node_numbers:
        raise RuntimeError("CCX Result has no NodeNumbers.")

    # Primary path: same helper provided by FEM result meshes.
    color_method = getattr(mesh.ViewObject, "setNodeColorByScalars", None)
    if callable(color_method):
        try:
            color_method(node_numbers, values)
        except Exception as exc:
            warn(f"setNodeColorByScalars failed, using NodeColor fallback: {exc}")
            color_method = None

    # Fallback: manual rainbow NodeColor if native API is not available.
    if not callable(color_method):
        vals = [to_float(v) for v in values]
        vals = [v for v in vals if v is not None and finite(v)]
        if not vals:
            raise RuntimeError(f"Result field {prop_name} does not contain numeric values.")

        vmin = min(vals)
        vmax = max(vals)
        span = vmax - vmin
        if abs(span) < 1e-15:
            span = 1.0

        def rainbow(t):
            # Blue -> cyan -> green -> yellow -> red
            t = max(0.0, min(1.0, t))
            if t < 0.25:
                q = t / 0.25
                return (0.0, q, 1.0)
            if t < 0.50:
                q = (t - 0.25) / 0.25
                return (0.0, 1.0, 1.0 - q)
            if t < 0.75:
                q = (t - 0.50) / 0.25
                return (q, 1.0, 0.0)
            q = (t - 0.75) / 0.25
            return (1.0, 1.0 - q, 0.0)

        colors = {}
        for n, v in zip(node_numbers, values):
            fv = to_float(v)
            if fv is None or not finite(fv):
                continue
            colors[int(n)] = rainbow((fv - vmin) / span)

        try:
            mesh.ViewObject.NodeColor = colors
        except Exception as exc:
            raise RuntimeError(f"Unable to set result color map: {exc}")

    try:
        mesh.ViewObject.DisplayMode = "Flat Lines"
    except Exception:
        try:
            mesh.ViewObject.DisplayMode = "Surface"
        except Exception:
            pass

    try:
        mesh.ViewObject.LineWidth = 1.0
    except Exception:
        pass

    return {
        "mesh": mesh,
        "values": values,
        "nodes": node_numbers,
        "unit": unit,
        "title": title,
    }


def apply_visual_displacement(mesh, factor):
    """Applies a visualization-only displacement factor."""
    if mesh is None or factor is None:
        return

    try:
        method = getattr(mesh.ViewObject, "applyDisplacement", None)
        if callable(method):
            method(float(factor))
            return
    except Exception:
        pass

    # Older API might have animate().
    try:
        method = getattr(mesh.ViewObject, "animate", None)
        if callable(method):
            method(float(factor))
    except Exception as exc:
        warn(f"Unable to apply visual displacement: {exc}")


def _get_active_view():
    """Returns the actual 3D ActiveView object."""
    try:
        view = Gui.ActiveDocument.ActiveView
        if view is not None:
            return view
    except Exception:
        pass

    try:
        view = Gui.activeDocument().activeView()
        if view is not None:
            return view
    except Exception:
        pass

    raise RuntimeError("Unable to obtain active 3D View.")


def _qt_modules_for_image():
    try:
        from PySide import QtCore, QtGui, QtSvg
        return QtCore, QtGui, QtSvg
    except Exception:
        pass

    try:
        from PySide6 import QtCore, QtGui, QtSvg
        return QtCore, QtGui, QtSvg
    except Exception as exc:
        raise RuntimeError(
            f"Unable to import PySide/PySide6 for image export: {exc}"
        )


def _render_svg_to_png(svg_path, png_path, width, height):
    """Rasterizes active 3D view SVG export via QtSvg."""
    QtCore, QtGui, QtSvg = _qt_modules_for_image()

    renderer = QtSvg.QSvgRenderer(svg_path)
    if not renderer.isValid():
        raise RuntimeError(f"SVG renderer rejected file: {svg_path}")

    image = QtGui.QImage(
        int(width), int(height), QtGui.QImage.Format_ARGB32
    )
    image.fill(QtCore.Qt.white)

    painter = QtGui.QPainter(image)
    try:
        renderer.render(painter)
    finally:
        painter.end()

    if not image.save(png_path, "PNG"):
        raise RuntimeError(f"Qt failed to save PNG: {png_path}")


def _save_active_view_image(view, png_path):
    """First uses native saveImage, then falls back to TechDraw SVG."""
    width = int(CONFIG["IMAGE_WIDTH"])
    height = int(CONFIG["IMAGE_HEIGHT"])

    # Native FreeCAD API – officially documented path.
    try:
        view.saveImage(
            png_path,
            width,
            height,
            "White"
        )
        if os.path.exists(png_path):
            return "saveImage"
    except Exception as exc:
        warn(f"ActiveView.saveImage is not available in this build or failed: {exc}")

    # Robust fallback: export active 3D view to SVG and rasterize.
    try:
        import TechDrawGui
        temp_svg = os.path.splitext(png_path)[0] + "_activeview.svg"
        options = {
            "width": 190.0,
            "height": 120.0,
            "paintBackground": True,
            "backgroundColor": (255, 255, 255, 255),
            "lineWidth": 0.6,
            "border": 2.0,
            "mode": 0,
        }
        TechDrawGui.copyActiveViewToSvgFile(
            App.ActiveDocument,
            temp_svg,
            options
        )
        _render_svg_to_png(
            temp_svg,
            png_path,
            width,
            height
        )
        return "TechDrawGui.copyActiveViewToSvgFile"
    except Exception as exc:
        raise RuntimeError(
            "Unable to save 3D view screenshot. "
            f"saveImage failed and fallback copyActiveViewToSvgFile failed: {exc}"
        )


def capture_iso_result_image(doc, result, mode, title, png_path, constraints=None):
    """Generates an ISO screenshot directly from the selected CCX Result."""
    if not getattr(App, "GuiUp", False):
        raise RuntimeError("FreeCAD GUI is not active.")

    view = _get_active_view()
    mesh = get_result_mesh(result)
    if mesh is None:
        raise RuntimeError("CCX Result has no result.Mesh.")

    old_visibility = {}
    old_background = None
    for obj in doc.Objects:
        try:
            old_visibility[obj.Name] = bool(obj.ViewObject.Visibility)
        except Exception:
            pass

    try:
        # Result CCX mesh is the only main scene object.
        for obj in doc.Objects:
            try:
                obj.ViewObject.Visibility = False
            except Exception:
                pass

        mesh.ViewObject.Visibility = True

        if CONFIG.get("SHOW_CONSTRAINT_SYMBOLS", True):
            for c in constraints or []:
                try:
                    c.ViewObject.Visibility = True
                except Exception:
                    pass

        # Result field + color map.
        set_result_scalar_display(result, mode)

        # Apply displacement identically to all three views for geometric comparability.
        # This is visualization only, not a new calculation.
        apply_visual_displacement(
            mesh,
            CONFIG.get("DISPLACEMENT_SCALE", 5.0)
        )

        # ISO / axonometric.
        try:
            view.viewAxonometric()
        except Exception:
            try:
                Gui.SendMsgToActiveView("ViewAxo")
            except Exception:
                pass

        try:
            view.fitAll()
        except Exception:
            try:
                Gui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass

        # Limit intrusive GUI elements.
        try:
            view.setAxisCross(False)
        except Exception:
            pass

        try:
            Gui.updateGui()
        except Exception:
            pass

        method = _save_active_view_image(view, png_path)

        log(f"Screenshot: {title} [{method}] -> {png_path}")

        if not os.path.exists(png_path):
            raise RuntimeError(f"Screenshot was not created: {png_path}")

    finally:
        for obj in doc.Objects:
            if obj.Name in old_visibility:
                try:
                    obj.ViewObject.Visibility = old_visibility[obj.Name]
                except Exception:
                    pass


def png_to_data_uri(path):
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        return "data:image/png;base64," + data
    except Exception as exc:
        warn(f"Unable to load PNG: {exc}")
        return ""


# ============================================================================
# SVG PRIMITIVES
# ============================================================================

COL = {
    "navy": "#123D68",
    "blue": "#1F67A5",
    "blue2": "#2D7BB8",
    "light": "#EAF2F8",
    "grid": "#A9BBC8",
    "text": "#1A2733",
    "muted": "#64717B",
    "white": "#FFFFFF",
    "green": "#198754",
    "orange": "#D98200",
    "red": "#B42318",
    "grey": "#F5F7F9",
}


def svg_rect(x, y, w, h, fill=COL["white"], stroke=COL["grid"], sw=1, rx=0):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" rx="{rx}"/>'
    )


def svg_line(x1, y1, x2, y2, stroke=COL["grid"], sw=1):
    return (
        f'<line x1="{x1}" y1="{y1}" '
        f'x2="{x2}" y2="{y2}" '
        f'stroke="{stroke}" stroke-width="{sw}"/>'
    )


def svg_text(
    x,
    y,
    text,
    size=10,
    bold=False,
    anchor="start",
    fill=COL["text"]
):
    size = float(size) * float(CONFIG.get("FONT_SCALE", 1.0))
    weight = 700 if bold else 400
    return (
        f'<text x="{x}" y="{y}" '
        f'font-family="DejaVu Sans, Arial, sans-serif" '
        f'font-size="{size:.2f}px" font-weight="{weight}" '
        f'text-anchor="{anchor}" fill="{fill}">{esc(text)}</text>'
    )


def svg_multiline_text(
    x,
    y,
    text,
    size=8.5,
    line_height=12,
    bold=False,
    fill=COL["text"],
    max_chars=105,
):
    """SVG text supporting hard breaks and automatic wrapping."""
    paragraphs = safe_str(text).splitlines() or [""]
    lines = []

    for paragraph in paragraphs:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue

        current = ""
        for word in words:
            trial = word if not current else current + " " + word
            if len(trial) > max_chars and current:
                lines.append(current)
                current = word
            else:
                current = trial
        if current:
            lines.append(current)

    weight = 700 if bold else 400
    scaled_size = float(size) * float(CONFIG.get("FONT_SCALE", 1.0))
    scaled_line = float(line_height) * float(CONFIG.get("FONT_SCALE", 1.0))

    chunks = [
        f'<text x="{x}" y="{y}" '
        f'font-family="DejaVu Sans, Arial, sans-serif" '
        f'font-size="{scaled_size:.2f}px" font-weight="{weight}" '
        f'fill="{fill}">'
    ]

    first = True
    for line in lines:
        dy = 0 if first else scaled_line
        chunks.append(
            f'<tspan x="{x}" dy="{dy:.2f}px">{esc(line)}</tspan>'
        )
        first = False

    chunks.append("</text>")
    return "".join(chunks)


def conclusion_box(elements, x, y, w, h, title, body, status="info"):
    """Conclusion block with deterministic one-sentence-per-line rendering.

    Do not use a single SVG <text> element with embedded newlines/tspan dy here:
    some FreeCAD/Qt SVG renderers collapse or inconsistently render those line breaks.
    Each wrapped line is therefore emitted as an independent <text> element.
    """
    fill = {
        "ok": "#EEF8F0",
        "warn": "#FFF8EA",
        "fail": "#FDEEEE",
        "info": "#F1F6FA",
    }.get(status, "#F1F6FA")
    stroke = {
        "ok": COL["green"],
        "warn": COL["orange"],
        "fail": COL["red"],
        "info": COL["blue"],
    }.get(status, COL["blue"])

    elements.append(svg_rect(x, y, w, h, fill, stroke, 1, 5))
    elements.append(svg_text(x + 12, y + 20, title, 10.5, True, fill=stroke))

    # Explicit line breaks = one sentence per line.
    paragraphs = safe_str(body).splitlines() or [""]

    # Wrap each sentence independently so a long sentence never merges
    # visually with the following sentence.
    max_chars = 112
    wrapped = []
    for paragraph in paragraphs:
        words = paragraph.split()
        if not words:
            wrapped.append("")
            continue

        line = ""
        for word in words:
            trial = word if not line else line + " " + word
            if len(trial) > max_chars and line:
                wrapped.append(line)
                line = word
            else:
                line = trial
        if line:
            wrapped.append(line)

    # Fixed line spacing. Independent <text> nodes are used for maximum
    # compatibility with QSvgRenderer / TechDraw / Qt PDF export.
    start_y = y + 43
    line_h = 12
    max_lines = max(1, int((h - 50) / line_h))

    for i, line in enumerate(wrapped[:max_lines]):
        elements.append(
            svg_text(
                x + 12,
                start_y + i * line_h,
                line,
                size=7.6,
                bold=False,
                fill=COL["text"],
            )
        )

    if len(wrapped) > max_lines:
        elements.append(
            svg_text(
                x + 12,
                start_y + (max_lines - 1) * line_h,
                "...",
                size=7.6,
                bold=True,
                fill=COL["text"],
            )
        )


def svg_image(x, y, w, h, data_uri):
    if not data_uri:
        return svg_text(
            x + w / 2,
            y + h / 2,
            "Image was not created.",
            12,
            True,
            "middle"
        )

    return (
        f'<image x="{x}" y="{y}" width="{w}" height="{h}" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'href="{data_uri}" xlink:href="{data_uri}"/>'
    )


def section_header(elements, x, y, w, title):
    elements.append(
        svg_rect(
            x, y, w, 25,
            fill=COL["navy"],
            stroke=COL["navy"]
        )
    )
    elements.append(
        svg_text(
            x + 10,
            y + 18,
            title,
            11,
            True,
            fill=COL["white"]
        )
    )


def key_value_table(elements, x, y, w, rows, row_h=24, first_col=0.48):
    total_h = row_h * len(rows)
    split = x + w * first_col

    elements.append(
        svg_rect(
            x, y, w, total_h,
            fill=COL["white"],
            stroke=COL["grid"]
        )
    )

    elements.append(
        svg_line(
            split, y,
            split, y + total_h,
            COL["grid"], 1
        )
    )

    for i, row in enumerate(rows):
        yy = y + i * row_h
        if i > 0:
            elements.append(
                svg_line(
                    x, yy,
                    x + w, yy,
                    COL["grid"], 1
                )
            )

        elements.append(
            svg_text(
                x + 7,
                yy + 16,
                row[0],
                8.7,
                True
            )
        )
        elements.append(
            svg_text(
                split + 7,
                yy + 16,
                compact_text(row[1], 65),
                8.7
            )
        )


def constraints_table(elements, x, y, w, constraints, max_rows=7):
    cols = [
        ("Type", 110),
        ("Name", 125),
        ("Reference", 225),
        ("Parameters", 274),
    ]

    header_h = 24
    row_h = 27

    rows = constraints[:max_rows]
    extra = len(constraints) - len(rows)
    if extra > 0:
        rows.append({
            "type": "...",
            "name": f"additional {extra}",
            "refs": "",
            "params": ""
        })

    height = header_h + row_h * len(rows)

    elements.append(
        svg_rect(
            x, y, w, height,
            fill=COL["white"],
            stroke=COL["grid"]
        )
    )

    # header
    elements.append(
        svg_rect(
            x, y, w, header_h,
            fill=COL["light"],
            stroke=COL["grid"]
        )
    )

    xpos = x
    for title, cw in cols:
        elements.append(
            svg_text(
                xpos + 5,
                y + 16,
                title,
                8.5,
                True
            )
        )
        xpos += cw
        if xpos < x + w:
            elements.append(
                svg_line(
                    xpos, y,
                    xpos, y + height,
                    COL["grid"]
                )
            )

    for i, row in enumerate(rows):
        yy = y + header_h + i * row_h
        if i > 0:
            elements.append(
                svg_line(
                    x, yy,
                    x + w, yy,
                    COL["grid"]
                )
            )

        values = (
            row["type"],
            row["name"],
            row["refs"],
            row["params"]
        )

        xpos = x
        for j, (_, cw) in enumerate(cols):
            elements.append(
                svg_text(
                    xpos + 5,
                    yy + 17,
                    compact_text(
                        values[j],
                        30 if j != 2 else 39
                    ),
                    7.5,
                    j == 0
                )
            )
            xpos += cw

    return height


def status_box(elements, x, y, w, h, title, value, status="info"):
    fill = {
        "ok": "#E8F5E9",
        "warn": "#FFF6E5",
        "fail": "#FCEAEA",
        "info": "#EEF5FA",
    }.get(status, "#EEF5FA")

    stroke = {
        "ok": COL["green"],
        "warn": COL["orange"],
        "fail": COL["red"],
        "info": COL["blue"],
    }.get(status, COL["blue"])

    elements.append(
        svg_rect(
            x, y, w, h,
            fill=fill,
            stroke=stroke,
            sw=1,
            rx=4
        )
    )
    elements.append(
        svg_text(
            x + 9,
            y + 17,
            title,
            7.5,
            True,
            fill=COL["muted"]
        )
    )
    elements.append(
        svg_text(
            x + 9,
            y + h - 10,
            value,
            13,
            True,
            fill=stroke
        )
    )


def legend(elements, x, y, w, h, min_value, max_value, unit):
    """Simple visual legend matching standard FEM rainbow map."""
    grad_id = "grad_" + re.sub(r"[^a-zA-Z0-9_]", "_", f"{x}_{y}_{w}_{h}")

    elements.append(
        f'<defs><linearGradient id="{grad_id}" x1="0" y1="1" x2="0" y2="0">'
        f'<stop offset="0%" stop-color="#2146E8"/>'
        f'<stop offset="25%" stop-color="#19CFF4"/>'
        f'<stop offset="50%" stop-color="#21D33D"/>'
        f'<stop offset="75%" stop-color="#FFE31A"/>'
        f'<stop offset="100%" stop-color="#E51E19"/>'
        f'</linearGradient></defs>'
    )

    elements.append(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
        f'fill="url(#{grad_id})" stroke="#606B73" stroke-width="1"/>'
    )

    elements.append(
        svg_text(
            x + w + 8,
            y + 8,
            fmt(max_value, 2, unit),
            7.2,
            True
        )
    )
    elements.append(
        svg_text(
            x + w + 8,
            y + h,
            fmt(min_value, 2, unit),
            7.2,
            True
        )
    )
    elements.append(
        svg_text(
            x + w + 8,
            y + h + 17,
            unit,
            7.2,
            False,
            fill=COL["muted"]
        )
    )


# ============================================================================
# SVG PAGE 1 – TEXT
# ============================================================================

def build_svg_page1(
    doc,
    analysis,
    result,
    pipeline,
    material,
    mesh_info,
    stats,
    constraints,
    safety_factor,
    stress_util,
    disp_util,
    output_path
):
    W = 794
    H = 1123

    project = CONFIG["PROJECT"] or object_label(doc)
    company = CONFIG["COMPANY"]
    author = CONFIG["AUTHOR"]
    stamp = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

    elements = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="210mm" height="297mm" viewBox="0 0 794 1123">',
        svg_rect(0, 0, W, H, COL["white"], COL["white"]),
        svg_rect(18, 18, W - 36, H - 36, COL["white"], "#222222", 2),
    ]

    # --------------------------------------------------------------
    # Header
    # --------------------------------------------------------------
    elements.append(svg_text(35, 45, CONFIG["REPORT_TITLE"], 15, True))
    elements.append(svg_text(35, 64, CONFIG["REPORT_SUBTITLE"], 8.2, False, fill=COL["muted"]))
    elements.append(svg_text(760, 41, company, 8.7, True, "end"))
    elements.append(svg_text(760, 57, f"Project: {project}", 7.6, False, "end"))
    elements.append(svg_text(760, 72, f"Author: {author}", 7.6, False, "end"))
    elements.append(svg_line(30, 84, 764, 84, COL["navy"], 2))

    # --------------------------------------------------------------
    # Selected CCX result
    # --------------------------------------------------------------
    elements.append(svg_rect(30, 95, 734, 39, COL["light"], COL["blue"], 1, 4))
    elements.append(svg_text(42, 111, "SELECTED CCX RESULT", 7.2, True, fill=COL["muted"]))
    elements.append(svg_text(42, 128, object_label(result), 12, True, fill=COL["navy"]))
    elements.append(
        svg_text(
            752, 120,
            compact_text(safe_str(getattr(result, "TypeId", "-")), 45),
            6.8,
            False,
            "end",
            COL["muted"]
        )
    )

    # --------------------------------------------------------------
    # 1 Model / 2 Material
    # --------------------------------------------------------------
    section_header(elements, 30, 147, 355, "1. MODEL OVERVIEW")
    key_value_table(
        elements, 30, 172, 355,
        [
            ("Project", project),
            ("Document", getattr(doc, "FileName", "unsaved document") or "unsaved document"),
            ("Analysis", object_label(analysis)),
            ("CCX Result", object_label(result)),
            ("PostPipeline", object_label(pipeline) if pipeline else "not found"),
        ],
        row_h=22
    )

    section_header(elements, 405, 147, 359, "2. MATERIAL PROPERTIES")
    if material:
        mat_rows = [
            ("Material", material["name"]),
            ("Young's modulus E", fmt(material["E_MPa"], 1, "MPa")),
            ("Poisson's ratio ν", fmt(material["nu"], 3)),
            ("Density ρ", fmt(material["rho"], 0, "kg/m³")),
            ("Yield strength Re", fmt(material["yield_MPa"], 1, "MPa")),
        ]
    else:
        mat_rows = [
            ("Material", "not found"),
            ("Young's modulus E", "not available"),
            ("Poisson's ratio ν", "not available"),
            ("Density ρ", "not available"),
            ("Yield strength Re", "not available"),
        ]
    key_value_table(elements, 405, 172, 359, mat_rows, row_h=22)

    # --------------------------------------------------------------
    # 3 Mesh / 4 BC
    # --------------------------------------------------------------
    section_header(elements, 30, 303, 355, "3. FEM MESH PARAMETERS")
    if mesh_info:
        fem_nodes = mesh_info.get("nodes")
        result_nodes = mesh_info.get("result_nodes")

        if fem_nodes is not None and result_nodes is not None:
            nodes_text = f"{fmt_int(fem_nodes)} / {fmt_int(result_nodes)}"
        elif fem_nodes is not None:
            nodes_text = f"{fmt_int(fem_nodes)} / n/a"
        elif result_nodes is not None:
            nodes_text = f"n/a / {fmt_int(result_nodes)}"
        else:
            nodes_text = "not available"

        mesh_rows = [
            ("Number of nodes (FEM / result)", nodes_text),
            ("Number of elements", fmt_int(mesh_info.get("elements"))),
            ("Element type", mesh_info.get("element_type", "not available")),
            ("Description", mesh_info.get("element_description", "not available")),
            ("Element distribution", mesh_info.get("distribution", "not available")),
        ]
    else:
        mesh_rows = [
            ("Number of nodes (FEM / result)", "not available"),
            ("Number of elements", "not available"),
            ("Element type", "not available"),
            ("Description", "not available"),
            ("Element distribution", "not available"),
        ]
    key_value_table(elements, 30, 328, 355, mesh_rows, row_h=21, first_col=0.50)

    section_header(elements, 405, 303, 359, "4. BOUNDARY CONDITIONS")
    crows = constraint_data(constraints)
    if not crows:
        crows = [{"type": "not found", "name": "-", "refs": "-", "params": "-"}]
    constraints_table(elements, 405, 328, 359, crows, max_rows=5)

    # --------------------------------------------------------------
    # 5 Main results
    # --------------------------------------------------------------
    section_header(elements, 30, 474, 734, "5. MAIN RESULTS OF SELECTED CCX RESULT")

    status_stress = "info"
    if stress_util is not None:
        status_stress = "ok" if stress_util <= 80.0 else ("warn" if stress_util <= 100.0 else "fail")

    status_disp = "info"
    if disp_util is not None:
        status_disp = "ok" if disp_util <= 80.0 else ("warn" if disp_util <= 100.0 else "fail")

    status_box(elements, 30, 507, 232, 62, "MAX. VON MISES STRESS", fmt(stats["vm_max"], 2, "MPa"), status_stress)
    status_box(elements, 281, 507, 232, 62, "MAX. DEFORMATION / DISPLACEMENT", fmt(stats["disp_max"], 2, "mm"), status_disp)
    status_box(elements, 532, 507, 232, 62, "MAX. PRINCIPAL STRESS", fmt(stats["pmax_max"], 2, "MPa"), "info")

    key_value_table(
        elements, 30, 583, 734,
        [
            ("von Mises – minimum / maximum", f"{fmt(stats['vm_min'], 3, 'MPa')} / {fmt(stats['vm_max'], 3, 'MPa')}"),
            ("Displacement magnitude – minimum / maximum", f"{fmt(stats['disp_min'], 5, 'mm')} / {fmt(stats['disp_max'], 5, 'mm')}"),
            ("Maximum principal stress – minimum / maximum", f"{fmt(stats['pmax_min'], 3, 'MPa')} / {fmt(stats['pmax_max'], 3, 'MPa')}"),
            ("Minimum principal stress – minimum / maximum", f"{fmt(stats['pmin_min'], 3, 'MPa')} / {fmt(stats['pmin_max'], 3, 'MPa')}"),
            ("Safety factor n = Re / σvM,max", fmt(safety_factor, 3, "", "cannot be determined")),
        ],
        row_h=23,
        first_col=0.46
    )

    # --------------------------------------------------------------
    # 6 Conclusion
    # --------------------------------------------------------------
    section_header(elements, 30, 724, 734, "6. CONCLUSION AND TECHNICAL ASSESSMENT")

    if safety_factor is not None and material:
        conclusion_status = "ok" if stress_util <= 80.0 else ("warn" if stress_util <= 100.0 else "fail")
    else:
        conclusion_status = "info"

    conclusion_body = (
        f"Stress: maximum von Mises stress = {fmt(stats['vm_max'], 2, 'MPa')}; maximum principal stress = {fmt(stats['pmax_max'], 2, 'MPa')}."
        + "\n"
        + (
            f"Yield strength Re = {fmt(material['yield_MPa'], 2, 'MPa')}; safety factor n = {fmt(safety_factor, 3)}; utilization = {fmt(stress_util, 1, '%')}."
            if material and safety_factor is not None
            else "Yield strength Re is not available; automatic safety-factor calculation was not performed."
        )
        + "\n"
        + f"Deformation: maximum displacement Umax = {fmt(stats['disp_max'], 3, 'mm')}."
        + "\n"
        + (
            f"Allowable displacement = {fmt(CONFIG['MAX_ALLOWED_DISPLACEMENT_MM'], 3, 'mm')}; criterion utilization = {fmt(disp_util, 1, '%')}."
            if disp_util is not None
            else "Allowable displacement Uallow is not defined in the report configuration."
        )
        + "\n"
        + f"Mesh: {fmt_int(mesh_info['nodes']) if mesh_info else 'not available'} FEM/result nodes; {fmt_int(mesh_info['elements']) if mesh_info else 'not available'} elements; {mesh_info['element_type'] if mesh_info else 'not available'}."
        + "\n"
        + "Model validity: local maxima at supports, sharp edges or point load applications may be singularities and require separate engineering verification."
    )

    conclusion_box(elements, 30, 749, 734, 176, "CONCLUSION", conclusion_body, conclusion_status)

    # --------------------------------------------------------------
    # 7 Traceability
    # --------------------------------------------------------------
    section_header(elements, 30, 938, 734, "7. IDENTIFICATION AND TRACEABILITY")
    key_value_table(
        elements, 30, 963, 734,
        [
            ("CCX Result object", object_label(result)),
            ("Internal Name", safe_str(getattr(result, "Name", "-"))),
            ("Result Mesh", object_label(get_result_mesh(result))),
            ("Object type", safe_str(getattr(result, "TypeId", "-"))),
            ("Report generation date", stamp),
        ],
        row_h=20,
        first_col=0.28
    )

    elements.append(svg_line(30, 1070, 764, 1070, COL["navy"], 1))
    elements.append(svg_text(35, 1088, company, 7.0, False, fill=COL["muted"]))
    elements.append(svg_text(760, 1088, "Page 1 / 2", 7.0, False, "end", COL["muted"]))
    elements.append(svg_text(760, 1104, "FreeCAD FEM / CalculiX", 6.5, False, "end", COL["muted"]))

    elements.append("</svg>")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(elements))

    return output_path


# ============================================================================
# SVG PAGE 2 – GRAPHICS
# ============================================================================

def build_svg_page2(
    doc,
    result,
    result_images,
    stats,
    output_path
):
    W = 794
    H = 1123

    project = CONFIG["PROJECT"] or object_label(doc)
    company = CONFIG["COMPANY"]

    elements = []
    elements.append(
        '<?xml version="1.0" encoding="UTF-8"?>'
    )
    elements.append(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="210mm" height="297mm" viewBox="0 0 794 1123">'
    )

    elements.append(
        svg_rect(0, 0, W, H, COL["white"], COL["white"])
    )
    elements.append(
        svg_rect(18, 18, W - 36, H - 36, COL["white"], "#222222", 2)
    )

    elements.append(
        svg_text(35, 48, "GRAPHICAL RESULTS – CCX RESULT", 14, True)
    )
    elements.append(
        svg_text(
            35,
            68,
            f"Result: {object_label(result)} | Project: {project}",
            7.8,
            False,
            fill=COL["muted"]
        )
    )
    elements.append(
        svg_line(30, 84, 764, 84, COL["navy"], 2)
    )

    block_x = 30
    block_w = 734
    image_x = 42

    LEGEND_SHIFT_MM = 15.0
    PX_PER_MM = 794.0 / 210.0
    legend_shift_px = LEGEND_SHIFT_MM * PX_PER_MM

    legend_w = 16
    legend_x = 711 - legend_shift_px

    image_w = 655 - legend_shift_px
    image_h = 220

    blocks = [
        (
            "CCX Result - Displacement magnitude (ISO view)",
            "Uabs",
            result_images.get("Uabs", ""),
            stats["disp_min"],
            stats["disp_max"],
            "mm"
        ),
        (
            "CCX Result - von Mises Stress (ISO view)",
            "Sabs",
            result_images.get("Sabs", ""),
            stats["vm_min"],
            stats["vm_max"],
            "MPa"
        ),
        (
            "CCX Result - Maximum principal stress (ISO view)",
            "MaxPrin",
            result_images.get("MaxPrin", ""),
            stats["pmax_min"],
            stats["pmax_max"],
            "MPa"
        ),
    ]

    y = 101

    for i, (title, mode, image_path, mn, mx, unit) in enumerate(blocks):
        block_h = 292

        elements.append(
            svg_rect(
                block_x,
                y,
                block_w,
                block_h,
                "#FAFCFD",
                COL["grid"],
                1,
                3
            )
        )

        elements.append(
            svg_rect(
                block_x,
                y,
                block_w,
                28,
                COL["navy"],
                COL["navy"]
            )
        )
        elements.append(
            svg_text(
                block_x + 10,
                y + 19,
                title,
                9,
                True,
                fill=COL["white"]
            )
        )

        elements.append(
            svg_image(
                image_x,
                y + 39,
                image_w,
                image_h,
                png_to_data_uri(image_path)
            )
        )

        elements.append(
            svg_rect(
                image_x,
                y + 269,
                480,
                16,
                COL["white"],
                COL["grid"]
            )
        )
        elements.append(
            svg_text(
                image_x + 7,
                y + 281,
                f"Min = {fmt(mn, 3, unit)}    |    Max = {fmt(mx, 3, unit)}    |    ISO / Axonometric",
                6.2,
                False,
                fill=COL["muted"]
            )
        )

        legend_y = y + 48
        if mn is not None and mx is not None:
            legend(
                elements,
                legend_x,
                legend_y,
                legend_w,
                180,
                mn,
                mx,
                unit
            )
        else:
            elements.append(
                svg_text(
                    legend_x + 8,
                    legend_y + 25,
                    "n/a",
                    7,
                    True,
                    "middle",
                    fill=COL["muted"]
                )
            )

        y += block_h + 12

    # Footer
    elements.append(svg_line(30, 1070, 764, 1070, COL["navy"], 1))
    elements.append(svg_text(35, 1088, company, 7.3, False, fill=COL["muted"]))
    elements.append(svg_text(760, 1088, "Page 2 / 2", 7.3, False, "end", COL["muted"]))

    elements.append("</svg>")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(elements))

    return output_path


# ============================================================================
# TECHDRAW PAGES
# ============================================================================

def create_techdraw_page(doc, svg_path, label):
    """Creates a single TechDraw page from an SVG template."""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    page_name = f"FEM_Report_Page_{stamp}"
    template_name = f"FEM_Report_Template_{stamp}"

    page = doc.addObject("TechDraw::DrawPage", page_name)
    template = doc.addObject(
        "TechDraw::DrawSVGTemplate",
        template_name
    )

    template.Label = f"FEM Report Template – {label}"
    template.Template = svg_path
    page.Template = template
    page.Label = label

    doc.recompute()
    return page


# ============================================================================
# MULTI-PAGE PDF VIA QT
# ============================================================================

def get_qt_modules():
    """
    FreeCAD typically uses PySide; older installations may use Qt5,
    newer ones Qt6. Returns QtCore, QtGui, QtSvg.
    """
    try:
        from PySide import QtCore, QtGui, QtSvg
        return QtCore, QtGui, QtSvg
    except Exception:
        pass

    try:
        from PySide6 import QtCore, QtGui, QtSvg
        return QtCore, QtGui, QtSvg
    except Exception as exc:
        raise RuntimeError(
            f"Unable to import QtCore/QtGui/QtSvg from PySide/PySide6: {exc}"
        )


def set_pdf_a4(pdf_writer, QtCore, QtGui):
    """Compatible A4 setting for Qt5/Qt6."""
    try:
        # Qt5
        if hasattr(pdf_writer, "setPageSizeMM"):
            pdf_writer.setPageSizeMM(
                QtCore.QSizeF(210.0, 297.0)
            )
            return
    except Exception:
        pass

    try:
        # Qt6
        qpagesize_cls = getattr(QtGui, "QPageSize")
        size_id = getattr(qpagesize_cls, "A4")
        pdf_writer.setPageSize(
            qpagesize_cls(size_id)
        )
        return
    except Exception:
        pass

    warn("Failed to explicitly set A4; default Qt PDF writer page size will be used.")


def export_multi_page_pdf(svg_paths, pdf_path):
    """
    Renders both SVG pages via QSvgRenderer to QPdfWriter.

    Advantages:
        - 1 PDF file,
        - 2 physical pages,
        - Report remains saved as SVG + separate PDF file; TechDraw pages are not created to ensure compatibility.
    """
    QtCore, QtGui, QtSvg = get_qt_modules()

    pdf_writer = QtGui.QPdfWriter(pdf_path)

    try:
        pdf_writer.setResolution(150)
    except Exception:
        pass

    set_pdf_a4(pdf_writer, QtCore, QtGui)

    painter = QtGui.QPainter(pdf_writer)
    if not painter.isActive():
        raise RuntimeError("QPainter failed to become active on the PDF writer.")

    try:
        for index, svg_path in enumerate(svg_paths):
            renderer = QtSvg.QSvgRenderer(svg_path)
            if not renderer.isValid():
                raise RuntimeError(
                    f"SVG renderer rejected file: {svg_path}"
                )

            rect = painter.viewport()
            renderer.render(painter, rect)

            if index < len(svg_paths) - 1:
                if hasattr(pdf_writer, "newPage"):
                    pdf_writer.newPage()
                else:
                    painter.end()
                    raise RuntimeError(
                        "The used Qt PDF writer does not support newPage()."
                    )
    finally:
        painter.end()

    if not os.path.exists(pdf_path):
        raise RuntimeError(
            "PDF writer finished operation, but the PDF file was not found."
        )


# ============================================================================
# OUTPUT PATHS
# ============================================================================

def choose_output_dir(default_dir):
    """
    Always displays an output folder selection dialog before generating the report.
    Cancel = safe exit without error traceback.
    """
    if not CONFIG.get("ASK_OUTPUT_DIR", True):
        return default_dir

    try:
        try:
            from PySide import QtWidgets
        except Exception:
            from PySide6 import QtWidgets

        selected = QtWidgets.QFileDialog.getExistingDirectory(
            None,
            "Select output folder for FEM report",
            default_dir
        )

        if not selected:
            log("Output folder selection cancelled. FEM report was not generated.")
            return None

        log(f"Output folder: {selected}")
        return selected

    except Exception as exc:
        warn(f"Output-folder dialog unavailable ({exc}); using default folder: {default_dir}")
        return default_dir


class OutputSelectionCancelled(Exception):
    """Internal control-flow exception used when the user cancels folder selection."""
    pass


def build_paths(doc, result):
    out_dir = choose_output_dir(CONFIG["OUTPUT_DIR"])
    if not out_dir:
        raise OutputSelectionCancelled()

    os.makedirs(out_dir, exist_ok=True)

    project = CONFIG["PROJECT"] or object_label(doc)
    safe_project = file_safe_name(project)
    safe_result = file_safe_name(object_label(result))
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    pdf_name = CONFIG["OUTPUT_FILE"]
    if not pdf_name:
        pdf_name = (
            f"{safe_project}_{safe_result}_FEM_Report_{stamp}.pdf"
        )

    return {
        "pdf": os.path.join(out_dir, pdf_name),
        "page1": os.path.join(
            out_dir,
            f"{safe_project}_{safe_result}_Report_Page1_{stamp}.svg"
        ),
        "page2": os.path.join(
            out_dir,
            f"{safe_project}_{safe_result}_Report_Page2_{stamp}.svg"
        ),
        "disp": os.path.join(
            out_dir,
            f"{safe_project}_{safe_result}_DisplacementMagnitude_ISO_{stamp}.png"
        ),
        "vm": os.path.join(
            out_dir,
            f"{safe_project}_{safe_result}_vonMises_ISO_{stamp}.png"
        ),
        "pmax": os.path.join(
            out_dir,
            f"{safe_project}_{safe_result}_MaximumPrincipalStress_ISO_{stamp}.png"
        ),
    }


# ============================================================================
# MAIN REPORT
# ============================================================================

def generate_selected_ccx_report(doc=None):
    if doc is None:
        doc = App.ActiveDocument

    if doc is None:
        raise RuntimeError("No active FreeCAD document is open.")

    if not getattr(App, "GuiUp", False):
        raise RuntimeError("This report requires the FreeCAD GUI.")

    log("")
    log("=" * 78)
    log("FEM ENGINEERING REPORT v7 – START")
    log("=" * 78)

    # ------------------------------------------------------------------
    # 1) Analysis
    # ------------------------------------------------------------------
    analysis = find_analysis(doc)
    if analysis is None:
        raise RuntimeError("FEM Analysis was not found.")
    log(f"Analysis: {object_label(analysis)}")

    # ------------------------------------------------------------------
    # 2) EXACTLY SELECTED CCX RESULT
    # ------------------------------------------------------------------
    result = find_selected_ccx_result(doc)
    log(f"Selected CCX Result: {object_label(result)}")
    log(f"Result Name: {safe_str(getattr(result, 'Name', '-'))}")
    log(f"Result TypeId: {safe_str(getattr(result, 'TypeId', '-'))}")

    # Keep the result actually selected in the GUI.
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(result)
    except Exception:
        pass

    # ------------------------------------------------------------------
    # 3) Pipeline info
    # ------------------------------------------------------------------
    pipeline = find_post_pipeline(doc, analysis)
    log(
        "PostPipeline: "
        + (object_label(pipeline) if pipeline else "not found")
    )

    # ------------------------------------------------------------------
    # 4) Material
    # ------------------------------------------------------------------
    material = find_material(doc, analysis)
    log(
        "Material: "
        + (material["name"] if material else "not found")
    )

    # ------------------------------------------------------------------
    # 5) Result data
    # ------------------------------------------------------------------
    ensure_result_arrays(result)
    stats = get_all_result_stats(result)

    log(
        f"Displacement magnitude: min={stats['disp_min']} mm, "
        f"max={stats['disp_max']} mm"
    )
    log(
        f"Von Mises: min={stats['vm_min']} MPa, "
        f"max={stats['vm_max']} MPa"
    )
    log(
        f"Maximum principal stress: min={stats['pmax_min']} MPa, "
        f"max={stats['pmax_max']} MPa"
    )

    # ------------------------------------------------------------------
    # 6) Mesh – DIRECTLY FROM SELECTED RESULT.MESH
    # ------------------------------------------------------------------
    result_mesh = get_result_mesh(result)
    mesh_info = mesh_statistics_with_result(result_mesh, result)

    if mesh_info:
        log(
            "Mesh: "
            f"{mesh_info['nodes']} nodes (FEM / result) / "
            f"{mesh_info['elements']} elements / "
            f"{mesh_info['element_type']} / "
            f"{mesh_info['kind']}"
        )
        log(
            "Mesh distribution: "
            f"{mesh_info['distribution']}"
        )
    else:
        warn("Result mesh statistics were not available.")

    # ------------------------------------------------------------------
    # 7) Constraints
    # ------------------------------------------------------------------
    constraints = find_constraints(analysis)
    log(f"Boundary conditions: {len(constraints)}")

    # ------------------------------------------------------------------
    # 8) Engineering checks
    # ------------------------------------------------------------------
    safety_factor = None
    stress_util = None

    Re = material["yield_MPa"] if material else None
    vm_max = stats["vm_max"]

    if (
        Re is not None
        and vm_max is not None
        and vm_max > 0
    ):
        safety_factor = Re / vm_max
        stress_util = 100.0 * vm_max / Re

    max_disp = CONFIG.get(
        "MAX_ALLOWED_DISPLACEMENT_MM"
    )

    disp_util = None
    if (
        max_disp is not None
        and stats["disp_max"] is not None
        and max_disp > 0
    ):
        disp_util = 100.0 * stats["disp_max"] / max_disp

    # ------------------------------------------------------------------
    # 9) Output paths
    # ------------------------------------------------------------------
    paths = build_paths(doc, result)

    # ------------------------------------------------------------------
    # 10) GRAPHICS – EXACTLY SELECTED RESULT
    # ------------------------------------------------------------------
    capture_iso_result_image(
        doc,
        result,
        "Uabs",
        "CCX Result - Displacement magnitude (ISO view)",
        paths["disp"],
        constraints
    )

    capture_iso_result_image(
        doc,
        result,
        "Sabs",
        "CCX Result - von Mises Stress (ISO view)",
        paths["vm"],
        constraints
    )

    capture_iso_result_image(
        doc,
        result,
        "MaxPrin",
        "CCX Result - Maximum principal stress (ISO view)",
        paths["pmax"],
        constraints
    )

    # ------------------------------------------------------------------
    # 11) SVG page 1
    # ------------------------------------------------------------------
    build_svg_page1(
        doc=doc,
        analysis=analysis,
        result=result,
        pipeline=pipeline,
        material=material,
        mesh_info=mesh_info,
        stats=stats,
        constraints=constraints,
        safety_factor=safety_factor,
        stress_util=stress_util,
        disp_util=disp_util,
        output_path=paths["page1"]
    )

    # ------------------------------------------------------------------
    # 12) SVG page 2
    # ------------------------------------------------------------------
    result_images = {
        "Uabs": paths["disp"],
        "Sabs": paths["vm"],
        "MaxPrin": paths["pmax"],
    }

    build_svg_page2(
        doc=doc,
        result=result,
        result_images=result_images,
        stats=stats,
        output_path=paths["page2"]
    )

    # ------------------------------------------------------------------
    # 13) Multi-page PDF
    # ------------------------------------------------------------------
    export_multi_page_pdf(
        [paths["page1"], paths["page2"]],
        paths["pdf"]
    )

    # ------------------------------------------------------------------
    # 15) Final GUI state – selected CCX Result + Uabs display
    # ------------------------------------------------------------------
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(result)

        for obj in doc.Objects:
            try:
                obj.ViewObject.Visibility = False
            except Exception:
                pass

        result_mesh.ViewObject.Visibility = True
        set_result_scalar_display(result, CONFIG["FINAL_RESULT_MODE"])
        apply_visual_displacement(
            result_mesh,
            CONFIG.get("DISPLACEMENT_SCALE", 5.0)
        )

        if CONFIG.get("SHOW_CONSTRAINT_SYMBOLS", True):
            for c in constraints:
                try:
                    c.ViewObject.Visibility = True
                except Exception:
                    pass

        view = _get_active_view()
        try:
            view.viewAxonometric()
        except Exception:
            pass
        try:
            view.fitAll()
        except Exception:
            pass

        Gui.updateGui()
    except Exception as exc:
        warn(f"Failed to restore the final GUI result state: {exc}")

    # ------------------------------------------------------------------
    # 16) Log
    # ------------------------------------------------------------------
    log("")
    log("=" * 78)
    log("FEM ENGINEERING REPORT v7 – COMPLETE")
    log("=" * 78)
    log(f"Selected Result : {object_label(result)}")
    log(f"PDF             : {paths['pdf']}")
    log(f"Text SVG        : {paths['page1']}")
    log(f"Graphic SVG     : {paths['page2']}")
    log(f"Displacement PNG: {paths['disp']}")
    log(f"von Mises PNG   : {paths['vm']}")
    log(f"Max Principal PNG: {paths['pmax']}")
    log("PDF pages        : 2 (SVG-rendered A4 pages)")
    log("=" * 78)

    return {
        "pdf": paths["pdf"],
        "page1_svg": paths["page1"],
        "page2_svg": paths["page2"],
        "disp_png": paths["disp"],
        "vm_png": paths["vm"],
        "pmax_png": paths["pmax"],
        "analysis": analysis,
        "result": result,
        "pipeline": pipeline,
        "material": material,
        "mesh": mesh_info,
        "stats": stats,
        "safety_factor": safety_factor,
        "stress_utilization": stress_util,
        "displacement_utilization": disp_util,
    }


# ============================================================================
# START
# ============================================================================

def main():
    try:
        return generate_selected_ccx_report()
    except OutputSelectionCancelled:
        return None
    except Exception:
        err("FEM report generation failed:")
        err(traceback.format_exc())
        return None


main()

