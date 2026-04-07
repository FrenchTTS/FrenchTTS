"""
FrenchTTS — What's New dialog shown once after an update.
"""

import customtkinter as ctk

from core.constants import APP_NAME
from ui.utils import _set_window_icon, apply_window_transparency


class WhatsNewWindow(ctk.CTkToplevel):
    """Modal-style window displayed once after each update.

    Shows the content of versions/{BUILD_ID}.md (YAML frontmatter already
    stripped by _load_changelog). Markdown headings and bullet points are
    rendered using tag_configure on the underlying tkinter.Text widget so no
    extra dependency is needed.
    """

    def __init__(self, app: "ctk.CTk", content: str):
        super().__init__(app)
        self.title(f"Nouveautés — {APP_NAME}")
        self.geometry("480x1")
        self.resizable(False, False)
        self.transient(app)
        self._build(content)
        self.update_idletasks()
        h = min(self.winfo_reqheight(), 540)
        self.geometry(f"480x{h}")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        _set_window_icon(self)
        self.after(50, self.lift)
        self.after(120, lambda: apply_window_transparency(self, app.opacity_var.get()))

    def _build(self, content: str) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self, text="Nouveautés",
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, pady=(16, 8))

        box = ctk.CTkTextbox(
            self, wrap="word", height=340,
            border_width=1, border_color=("gray70", "#3a3a3a"))
        box.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 10))

        # Apply markdown rendering via tags on the underlying tkinter.Text.
        t = box._textbox
        t.tag_configure("h2",     font=ctk.CTkFont(size=15, weight="bold"),
                        spacing1=10, spacing3=6)
        t.tag_configure("h3",     font=ctk.CTkFont(size=12, weight="bold"),
                        spacing1=8,  spacing3=3)
        t.tag_configure("bullet", lmargin1=10, lmargin2=22,
                        font=ctk.CTkFont(size=12), spacing3=2)
        t.tag_configure("normal", font=ctk.CTkFont(size=12))

        for line in content.split("\n"):
            if line.startswith("## "):
                t.insert("end", line[3:] + "\n", "h2")
            elif line.startswith("### "):
                t.insert("end", line[4:] + "\n", "h3")
            elif line.startswith("- "):
                t.insert("end", "  •  " + line[2:] + "\n", "bullet")
            else:
                t.insert("end", line + "\n", "normal")

        box.configure(state="disabled")

        ctk.CTkButton(
            self, text="Fermer", width=120,
            command=self.destroy
        ).grid(row=2, column=0, pady=(0, 14))
