# Current state

## Drawing

**DISPLAY ▸ Draw** provides manual area, line, and pin annotations on the globe.
The user clicks vertices and finishes with a double-click or Enter, or cancels
with Esc. Labels and colors are optional. Finished marks use the annotation
engine and its persistence and clear behavior. Areas and routes are draped on
the surface, so vertex altitude is not a placement guarantee.

## First-run experience

A surface class that never clears means no launcher for that page. The first-run
launcher waits for the exclusive surface to clear; it does not time out and
appear over a recording or clean-view session.
