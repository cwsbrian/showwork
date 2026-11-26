# Diagram Design in Showwork

Showwork includes [Diagram Design](https://github.com/cathrynlavery/diagram-design) at `../vendor/diagram-design/` (upstream commit `b228c5d77794a84150fca41b22940bb316b1398d`, MIT license in that folder). Use it for a diagram when connected shapes explain the result better than a short sentence, table, screenshot, or simple comparison. Useful types include flowchart, sequence, architecture delta, ER, and state machine. The bundled skill's `SKILL.md` selects a type; read only that type's reference and the supporting rules it names.

For Showwork reports, the user has chosen the app's existing visual identity. This integration supplies the brand choice, so skip Diagram Design's first-run brand question and use these roles instead of its shipped orange palette: `paper #fff`, `paper-2 #eef3f0`, `ink #172f34`, `muted #52696b`, `soft #52696b`, `rule #d9e3e0`, `accent #116e60`, `accent-tint #e8f5ed`, `link #2e5aa8`. Use system sans and mono font stacks with Korean fallbacks. Do not fetch Google Fonts in the app. Keep Diagram Design's layout, accessibility, density, and geometry rules.

Draw the standalone Diagram Design `.html` file in the temporary directory returned by `companion.py path`, next to the report JSON. Run the bundled `scripts/self_check.py` and `scripts/verify_geometry.py` against that file, then inspect a rendered preview at the size readers will see. Keep the source HTML in `/tmp`, not in the project. Static diagrams are supported; Showwork's report frame does not run scripts or animation controls.

In a handoff section or decision option, set `diagram` to the HTML filename instead of `html` or `image`:

```json
{"kind":"explanation","title":"Request path","body":"The request reaches the service through the gateway.","diagram":"request-path.html"}
```

`companion.py publish` keeps the diagram's inline CSS and SVG, strips its standalone page wrapper and external font link, and embeds the result as a locally scrollable Showwork visual. The SVG text stays selectable for inline comments. A source file outside the report's temporary directory, a missing SVG/style, or a script is rejected. Label a drawn proposal as a proposal and an explanatory diagram as an explanation; a Diagram Design visual is not runtime evidence.

If a source image or actual app screen is the evidence, use the normal `image` field and give its capture details. If a table or a sentence carries the point, use that instead of a diagram.
