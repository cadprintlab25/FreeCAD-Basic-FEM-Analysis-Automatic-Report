# 🔧 Automatic basic FEM Report from FreeCAD

Do you use FreeCAD + FEM Workbench + CalculiX and manually compile results into a PDF after every calculation?

I created the **"FEM Engineering Report"** tool to automate this entire step.

Once the FEM calculation is complete, simply select the desired CCX Result in the Tree View and run the script inside FreeCAD's Python console.

---

## 📄 What the Report Contains

It automatically generates a clear, professional two-page A4 PDF report containing:

* **Page 1 – Technical Report:**
  * Model and material information ($E$, $\nu$, $\rho$, $R_e$)
  * Number of FEM nodes / result nodes
  * Number and type of elements ($C3D10$, etc.)
  * Boundary conditions and loads (Fixed supports, forces, etc.)
  * Maximum von Mises stress, maximum displacement, and principal stresses
  * Automated calculation statistics and utilization check
  * Technical conclusion and traceability info
* **Page 2 – Graphical Results:**
  * 3D ISO graphical results with a color map:
    * Displacement magnitude ($U_{abs}$)
    * von Mises Stress ($S_{abs}$)
    * Maximum Principal Stress ($\text{MaxPrin}$)

Individual result images can also be saved automatically in PNG format alongside the final PDF.

---

## 📌 Suitable For

Design engineers, FEM analysts, product developers, engineering students, and small engineering firms who want to quickly create professional-looking documentation without manually transcribing results.

---

## 💻 Workflow

```text
FreeCAD + CalculiX → FEM calculation → Automated PDF report
```

1. Open your completed FEM model in FreeCAD.
2. Select the required `CCX_Resultsxxx` object in the Tree View.
3. Open **View -> Panels -> Python console**.
4. Paste and run the script (`FreeCAD_FEM_Report_Script.py`).
5. Choose your target output folder, and your professional multi-page PDF report is ready!

---

## ⚠️ Important Notice

The generated results are directly tied to the FEM calculation. Any changes to the geometry, material properties, mesh density, or boundary conditions require re-running the simulation to ensure report accuracy.

---

## 📄 License

Feel free to use, modify, and share this script for your engineering projects!