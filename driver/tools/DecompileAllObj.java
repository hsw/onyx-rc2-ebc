// SPDX-License-Identifier: MIT
// DecompileAllObj.java -- Ghidra headless postScript: decompile every function of the current program (used for the
// public rychly .uu objects, ELF relocatable, imported with normal analysis so relocations/symbols are applied).
// Args: <out.c>   (appends; the caller truncates the file before the first object)
// The objects are only read by Ghidra, never executed.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class DecompileAllObj extends GhidraScript {
  public void run() throws Exception {
    String out = getScriptArgs()[0];
    DecompInterface d = new DecompInterface();
    DecompileOptions o = new DecompileOptions();
    o.grabFromProgram(currentProgram);
    d.setOptions(o);
    d.toggleCCode(true);
    d.toggleSyntaxTree(true);
    d.setSimplificationStyle("decompile");
    d.openProgram(currentProgram);
    PrintWriter pw = new PrintWriter(new FileWriter(out, true));
    pw.println("\n/* ================= object " + currentProgram.getName() + " (Ghidra "
        + ghidra.framework.Application.getApplicationVersion() + ") ================= */\n");
    int n = 0;
    for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
      if (f.isExternal() || f.isThunk()) continue;
      DecompileResults r = d.decompileFunction(f, 300, monitor);
      pw.println("// ===== " + currentProgram.getName() + ":" + f.getName() + " @ " + f.getEntryPoint()
          + " (" + f.getBody().getNumAddresses() + " bytes)");
      if (r != null && r.decompileCompleted()) pw.println(r.getDecompiledFunction().getC());
      else pw.println("// decompile failed: " + (r == null ? "null" : r.getErrorMessage()));
      n++;
    }
    pw.close();
    println("DecompileAllObj: " + currentProgram.getName() + ": " + n + " functions");
  }
}
