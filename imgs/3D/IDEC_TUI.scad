//
// IDEC-TUI cube
// v6 - configurable wrapped text + forced new lines on all six faces
//
// Each face has the same IDEC-TUI banner plus a separate block of body text.
// Body text is left aligned, wrapped at spaces, supports forced new lines, and stays inside margins.
//


// ============================================================================
// USER TEXT - EDIT THIS SECTION
// ============================================================================
//
// Face mapping:
//   face1 = front  (+Y)
//   face2 = back   (-Y)
//   face3 = right  (+X)
//   face4 = left   (-X)
//   face5 = top    (+Z)
//   face6 = bottom (-Z)
//

// Each face is a LIST of paragraphs / forced lines.
//
// - Each quoted entry starts on a new line.
// - Long entries still word-wrap automatically.
// - An empty string "" inserts a blank line.
//
// Example:
//
// face1 = [
//     "This is a long paragraph that will wrap automatically.",
//     "",
//     "This begins a new paragraph.",
//     "This is explicitly another new line."
// ];
//
face1 = [
    "An IDEC PLC control and monitoring",
    "user interface.",
    "",
    "For Linux and Windows.",
    "",
    "Direct access to PLC data and I/O."
];

face2 = [
    "Features:",
    "",
    "Read and write PLC registers.",
    "Read, force, and release I/O.",
    "Hardware inventory and diagnostics.",
    "Built-in scripting,",
    "and emulation."
];

face3 = [
    "Usage:",
    "",
    "Connect to a PLC over serial.",
    "Read or write from the command prompt.",
    "Run .plc scripts for repeatable tests.",
    "Use help to explore commands."
];

face4 = [
    "Scripting:",
    "",
    "Variables, loops, and conditionals.",
    "Read and write PLC data.",
    "Control outputs and delays.",
    "Build simple automated test routines."
];

face5 = [
    "Diagnostics:",
    "",
    "Check PLC status and errors.",
    "Inspect connected expansion modules.",
    "Monitor hardware and system registers.",
    "Useful for setup and bench testing."
];

face6 = [
    "IDEC-TUI",
    "",
    "Open source.",
    "Terminal focused.",
    "",
    "github.com/FOSSBOSS/IDEC-TUI"
];

// ============================================================================
// BODY TEXT SETTINGS
// ============================================================================

body_font = "Liberation Sans:style=Regular";
body_size = 5.5;
body_color = [0, 0, 0];

// Left and right margin from the cube edges.
body_margin_x = 8;

// Distance below the red banner line before body text starts.
body_top_gap = 7;

// Bottom margin.
body_margin_bottom = 8;

// Distance from one text baseline to the next, as a multiple of body_size.
body_line_spacing = 1.35;

// OpenSCAD's normal text() does not automatically word-wrap.
// This wrapper breaks at spaces using this approximate maximum line length.
// Reduce this value for wider fonts or larger margins.
body_chars_per_line = 32;

body_text_th = 0.55;


// ============================================================================
// CUBE / BANNER SETTINGS
// ============================================================================

cube_side = 128;
img_w = 1280;
img_h = 225;

banner_h = cube_side * img_h / img_w;
top_margin = 5;
art_th = 1.0;
eps = 0.02;

banner_font = "Liberation Sans:style=Bold";

red    = [0.85, 0.10, 0.10];
blue   = [0.12, 0.42, 0.62];
yellow = [0.93, 0.76, 0.05];

$fn = 64;


// ============================================================================
// SIMPLE WORD WRAPPER
// ============================================================================
//
// The stable OpenSCAD text() primitive renders one line at a time, so these
// functions split a string into lines before rendering it.
//

function _skip_spaces(s, i) =
    i >= len(s) ? i :
    s[i] == " " ? _skip_spaces(s, i + 1) : i;

function _prev_space(s, first, i) =
    i <= first ? -1 :
    s[i] == " " ? i : _prev_space(s, first, i - 1);

function _line_end(s, first, max_chars) =
    let(limit = min(first + max_chars, len(s)))
    limit >= len(s) ? len(s) :
    let(sp = _prev_space(s, first, limit))
    sp >= first ? sp : limit;

function _string_range(s, first, last_exclusive) =
    first >= last_exclusive || first >= len(s) ? "" :
    str(s[first], _string_range(s, first + 1, last_exclusive));

function wrap_text(s, max_chars, first=0) =
    let(start = _skip_spaces(s, first))
    start >= len(s) ? [] :
    let(stop = _line_end(s, start, max_chars))
    concat(
        [_string_range(s, start, stop)],
        wrap_text(s, max_chars, _skip_spaces(s, stop))
    );


// Wrap a list of user-supplied paragraphs / forced lines.
//
// Each list entry begins on a new line.
// Empty entries are preserved as blank lines.
// Long entries are word-wrapped using body_chars_per_line.
//
// A plain string is also accepted for backward compatibility.
function wrap_face_text(txt, max_chars, i=0) =
    is_string(txt) ? wrap_text(txt, max_chars) :
    i >= len(txt) ? [] :
    concat(
        txt[i] == "" ? [""] : wrap_text(txt[i], max_chars),
        wrap_face_text(txt, max_chars, i + 1)
    );


// ============================================================================
// 2D LOGO PARTS
// ============================================================================

module gear_2d(outer_r=10, inner_r=6.5, teeth=12, tooth_w=2.6, tooth_h=3.0) {
    difference() {
        union() {
            circle(r=outer_r);

            for (a = [0 : 360/teeth : 360 - 360/teeth]) {
                rotate(a)
                translate([-tooth_w/2, outer_r - 0.2])
                square([tooth_w, tooth_h]);
            }
        }

        circle(r=inner_r);
    }
}


module tree_arrow_2d(s=1.0) {
    scale([s, s])
    polygon(points=[
        [ 0.0,  7.2],
        [-2.7,  4.4],
        [-1.0,  4.4],
        [-4.2,  1.4],
        [-1.5,  1.4],
        [-5.0, -2.2],
        [-0.9, -0.8],
        [-0.9, -6.0],
        [ 0.9, -6.0],
        [ 0.9, -0.8],
        [ 5.0, -2.2],
        [ 1.5,  1.4],
        [ 4.2,  1.4],
        [ 1.0,  4.4],
        [ 2.7,  4.4]
    ]);
}


// ============================================================================
// BODY TEXT
// ============================================================================

module body_text_block(txt=[], face_name="face") {
    y_top = cube_side / 2 - top_margin;
    y_bar = y_top - banner_h;

    x_left = -cube_side / 2 + body_margin_x;
    text_top = y_bar - body_top_gap;
    text_bottom = -cube_side / 2 + body_margin_bottom;

    step = body_size * body_line_spacing;
    max_lines = floor((text_top - text_bottom) / step) + 1;
    lines = wrap_face_text(txt, body_chars_per_line);

    if (len(lines) > max_lines)
        echo(str("WARNING: ", face_name, " has ", len(lines),
            " wrapped lines but only ", max_lines, " fit on the face."));

    if (len(lines) > 0)
        color(body_color)
        for (i = [0 : min(len(lines), max_lines) - 1]) {
            translate([x_left, text_top - i * step, 0])
            linear_extrude(height=body_text_th)
            text(
                lines[i],
                size=body_size,
                font=body_font,
                halign="left",
                valign="top"
            );
        }
}


// ============================================================================
// FACE ART
// ============================================================================
//
// Local coordinates:
//   +X = viewer's right
//   +Y = viewer's up
//   +Z = outward from the face
//

module face_art(body_txt=[], face_name="face") {
    y_top = cube_side / 2 - top_margin;
    y_bar = y_top - banner_h;
    bar_h = banner_h * 0.18;

    logo_x = -cube_side * 0.38;
    logo_y = y_bar + banner_h * 0.62;

    gear_or = banner_h * 0.28;
    gear_ir = gear_or * 0.62;
    tooth_w = gear_or * 0.28;
    tooth_h = gear_or * 0.34;
    tree_s  = gear_or * 0.10;

    // Center the IDEC-TUI title in the open area to the right of the logo.
    title_x = cube_side * 0.10;
    title_y = y_bar + banner_h * 0.64;
    title_size = banner_h * 0.56;

    // Solid red line
    color(red)
    linear_extrude(height=art_th)
    translate([-cube_side/2, y_bar])
    square([cube_side, bar_h]);

    // Blue gear
    color(blue)
    linear_extrude(height=art_th)
    translate([logo_x, logo_y])
    gear_2d(
        outer_r=gear_or,
        inner_r=gear_ir,
        teeth=12,
        tooth_w=tooth_w,
        tooth_h=tooth_h
    );

    // Yellow center tree/arrow
    color(yellow)
    linear_extrude(height=art_th)
    translate([logo_x, logo_y - gear_or * 0.02])
    tree_arrow_2d(s=tree_s);

    // Red IDEC-TUI title
    color(red)
    linear_extrude(height=art_th)
    translate([title_x, title_y])
    text(
        "IDEC-TUI",
        size=title_size,
        font=banner_font,
        halign="center",
        valign="center"
    );

    // User-supplied black body text
    body_text_block(body_txt, face_name);
}


// ============================================================================
// FACE PLACEMENT
// ============================================================================
//
// These are proper rotations, not reflections, so all text is readable from
// outside the cube.
//

// face1: Front (+Y)
module place_front(txt=[]) {
    multmatrix([
        [-1, 0, 0, 0],
        [ 0, 0, 1, cube_side/2 + eps],
        [ 0, 1, 0, 0],
        [ 0, 0, 0, 1]
    ])
    face_art(txt, "face1");
}


// face2: Back (-Y)
module place_back(txt=[]) {
    multmatrix([
        [1, 0,  0, 0],
        [0, 0, -1, -cube_side/2 - eps],
        [0, 1,  0, 0],
        [0, 0,  0, 1]
    ])
    face_art(txt, "face2");
}


// face3: Right (+X)
module place_right(txt=[]) {
    multmatrix([
        [0, 0, 1, cube_side/2 + eps],
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1]
    ])
    face_art(txt, "face3");
}


// face4: Left (-X)
module place_left(txt=[]) {
    multmatrix([
        [ 0, 0, -1, -cube_side/2 - eps],
        [-1, 0,  0, 0],
        [ 0, 1,  0, 0],
        [ 0, 0,  0, 1]
    ])
    face_art(txt, "face4");
}


// face5: Top (+Z)
module place_top(txt=[]) {
    multmatrix([
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, cube_side/2 + eps],
        [0, 0, 0, 1]
    ])
    face_art(txt, "face5");
}


// face6: Bottom (-Z)
module place_bottom(txt=[]) {
    multmatrix([
        [1,  0,  0, 0],
        [0, -1,  0, 0],
        [0,  0, -1, -cube_side/2 - eps],
        [0,  0,  0, 1]
    ])
    face_art(txt, "face6");
}


// ============================================================================
// MAIN MODEL
// ============================================================================

color("white")
cube(cube_side, center=true);

place_front(face1);
place_back(face2);
place_right(face3);
place_left(face4);
place_top(face5);
place_bottom(face6);
