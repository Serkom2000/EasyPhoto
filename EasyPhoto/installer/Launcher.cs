using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
using System.Management.Automation;
using System.Management.Automation.Runspaces;
using System.Threading;
class Entry {
  [STAThread] static void Main() {
    string root = AppDomain.CurrentDomain.BaseDirectory;
#if SETUP
    bool setup = true;
#else
    bool setup = false;
#endif
    string script = Path.Combine(root, setup ? "installer\\install.ps1" : "scripts\\launch.ps1");
    try {
      Environment.CurrentDirectory = root;
      using (var runspace = RunspaceFactory.CreateRunspace()) {
        runspace.ApartmentState = ApartmentState.STA;
        runspace.ThreadOptions = PSThreadOptions.ReuseThread;
        runspace.Open();
        using (var shell = PowerShell.Create()) {
          shell.Runspace = runspace;
          shell.AddScript("Set-ExecutionPolicy -Scope Process Bypass -Force; & '" + script.Replace("'", "''") + "'");
          shell.Invoke();
          if (shell.HadErrors) {
            string details = String.Join(Environment.NewLine, shell.Streams.Error);
            File.WriteAllText(Path.Combine(root, "startup-error.log"), details);
            MessageBox.Show("EasyPhoto could not open. See startup-error.log in the application folder.", "EasyPhoto");
          }
        }
      }
    } catch (Exception e) { MessageBox.Show(e.Message, "EasyPhoto"); }
  }
}
