//! A laid-out tree as SVG, drawn like Blender's Node Editor: frames under links under nodes; a node's header in its
//! category's color, its sockets colored by type, an unlinked input's
//! value in a field. Colors are CSS classes (`cat-geometry`, `ty-float`)
//! the page themes, but a color written in the text, which is inline.

use std::fmt::Write;

use crate::graph::Tree;
use crate::layout::{layout, Rect, CHAR_W, FRAME_TITLE_H, HEADER_H, NOTE_BAR, NOTE_LINE, NOTE_PAD};

const SOCKET_R: f64 = 4.5;
const MARGIN: f64 = 40.0;

pub fn svg(tree: &Tree) -> String {
    let l = layout(tree);
    let b = l.bounds;
    let mut s = String::new();
    let _ = write!(
        s,
        r#"<svg xmlns="http://www.w3.org/2000/svg" class="bn-graph" viewBox="{} {} {} {}" data-x="{}" data-y="{}" data-w="{}" data-h="{}">"#,
        f(b.x - MARGIN),
        f(b.y - MARGIN),
        f(b.w + 2.0 * MARGIN),
        f(b.h + 2.0 * MARGIN),
        f(b.x - MARGIN),
        f(b.y - MARGIN),
        f(b.w + 2.0 * MARGIN),
        f(b.h + 2.0 * MARGIN),
    );
    s.push_str(r#"<g class="frames">"#);
    for (frame, rect) in tree.frames.iter().zip(&l.frames) {
        let Some(r) = rect else { continue };
        let class = if frame.zone { "frame zone" } else { "frame" };
        let style = frame
            .color
            .as_ref()
            .map(|c| format!(r#" style="fill:{};fill-opacity:.32""#, esc(c)))
            .unwrap_or_default();
        let _ = write!(
            s,
            r#"<g class="{class}"><rect x="{}" y="{}" width="{}" height="{}" rx="6"{style}/><text class="frame-label" x="{}" y="{}">{}</text></g>"#,
            f(r.x),
            f(r.y),
            f(r.w),
            f(r.h),
            f(r.x + 10.0),
            f(r.y + FRAME_TITLE_H / 2.0 + 5.0),
            esc(&frame.label),
        );
    }
    // The comments of the text, in boxes like the add-on's in Blender.
    s.push_str(r#"</g><g class="notes">"#);
    for note in &l.notes {
        let r = note.rect;
        let _ = write!(
            s,
            r#"<g class="note"><rect class="note-box" x="{}" y="{}" width="{}" height="{}" rx="3"/><rect class="note-bar" x="{}" y="{}" width="{}" height="{}"/><text class="note-text">"#,
            f(r.x),
            f(r.y),
            f(r.w),
            f(r.h),
            f(r.x),
            f(r.y),
            f(NOTE_BAR),
            f(r.h),
        );
        for (i, line) in note.lines.iter().enumerate() {
            let _ = write!(
                s,
                r#"<tspan x="{}" y="{}">{}</tspan>"#,
                f(r.x + NOTE_BAR + NOTE_PAD),
                f(r.y + NOTE_PAD + NOTE_LINE * (i as f64 + 1.0) - 3.5),
                esc(line),
            );
        }
        s.push_str("</text></g>");
    }
    s.push_str(r#"</g><g class="links">"#);
    for (n, node) in tree.nodes.iter().enumerate() {
        for (i, input) in node.inputs.iter().enumerate() {
            let Some((from, o)) = input.link else {
                continue;
            };
            let [x1, y1] = l.output_at(from, o);
            let [x2, y2] = l.input_at(tree, n, i);
            let dx = ((x2 - x1).abs() * 0.5).max(40.0);
            let ty = tree.nodes[from].outputs[o]
                .ty
                .as_deref()
                .or(input.ty.as_deref());
            let _ = write!(
                s,
                r#"<path class="link {}" d="M{} {}C{} {} {} {} {} {}"/>"#,
                ty_class(ty),
                f(x1),
                f(y1),
                f(x1 + dx),
                f(y1),
                f(x2 - dx),
                f(y2),
                f(x2),
                f(y2),
            );
        }
    }
    s.push_str(r#"</g><g class="nodes">"#);
    for (n, node) in tree.nodes.iter().enumerate() {
        let r = l.nodes[n];
        let _ = write!(
            s,
            r#"<g class="node cat-{}" data-line="{}"><rect class="node-body" x="{}" y="{}" width="{}" height="{}" rx="5"/>"#,
            node.category.class(),
            node.line,
            f(r.x),
            f(r.y),
            f(r.w),
            f(r.h),
        );
        let style = node
            .color
            .as_ref()
            .map(|c| format!(r#" style="fill:{}""#, esc(c)))
            .unwrap_or_default();
        let _ = write!(
            s,
            r#"<path class="node-header" d="{}"{style}/><text class="node-title" x="{}" y="{}">{}</text>"#,
            header_path(r, 5.0),
            f(r.x + 10.0),
            f(r.y + HEADER_H / 2.0 + 4.0),
            esc(&fit(&node.title, r.w - 20.0)),
        );
        for (o, out) in node.outputs.iter().enumerate() {
            let [x, y] = l.output_at(n, o);
            let _ = write!(
                s,
                r#"<text class="socket-label out" x="{}" y="{}">{}</text>"#,
                f(x - 10.0),
                f(y + 4.0),
                esc(&fit(&out.name, r.w - 20.0)),
            );
            socket(&mut s, x, y, out.ty.as_deref());
        }
        for (i, setting) in node.settings.iter().enumerate() {
            let [x, y] = l.setting_at(tree, n, i);
            let _ = write!(
                s,
                r#"<rect class="menu" x="{}" y="{}" width="{}" height="18" rx="3"/><text class="menu-label" x="{}" y="{}">{}</text><path class="menu-arrow" d="M{} {}l3.5 3.5l3.5-3.5"/>"#,
                f(x + 8.0),
                f(y - 9.0),
                f(r.w - 16.0),
                f(x + 14.0),
                f(y + 4.0),
                esc(&fit(setting, r.w - 40.0)),
                f(x + r.w - 23.0),
                f(y - 2.0),
            );
        }
        for (i, input) in node.inputs.iter().enumerate() {
            let [x, y] = l.input_at(tree, n, i);
            match &input.value {
                Some(value) => {
                    let _ = write!(
                        s,
                        r#"<rect class="field" x="{}" y="{}" width="{}" height="16" rx="3"/>"#,
                        f(x + 8.0),
                        f(y - 8.0),
                        f(r.w - 16.0),
                    );
                    let room = r.w - 30.0;
                    let value = fit(value, room * 0.6);
                    let name_room = room - value.chars().count() as f64 * CHAR_W - 8.0;
                    if !input.name.is_empty() {
                        let _ = write!(
                            s,
                            r#"<text class="socket-label" x="{}" y="{}">{}</text>"#,
                            f(x + 14.0),
                            f(y + 4.0),
                            esc(&fit(&input.name, name_room)),
                        );
                    }
                    let _ = write!(
                        s,
                        r#"<text class="field-value" x="{}" y="{}">{}</text>"#,
                        f(x + r.w - 14.0),
                        f(y + 4.0),
                        esc(&value),
                    );
                }
                None => {
                    let _ = write!(
                        s,
                        r#"<text class="socket-label" x="{}" y="{}">{}</text>"#,
                        f(x + 10.0),
                        f(y + 4.0),
                        esc(&fit(&input.name, r.w - 20.0)),
                    );
                }
            }
            socket(&mut s, x, y, input.ty.as_deref());
        }
        s.push_str("</g>");
    }
    s.push_str("</g></svg>");
    s
}

fn socket(s: &mut String, x: f64, y: f64, ty: Option<&str>) {
    let _ = write!(
        s,
        r#"<circle class="socket {}" cx="{}" cy="{}" r="{SOCKET_R}"/>"#,
        ty_class(ty),
        f(x),
        f(y),
    );
}

/// The class of a socket type: `ty-float`, `ty-geometry`; `ty-any`
/// when unknown.
fn ty_class(ty: Option<&str>) -> String {
    match ty {
        Some(t) if !t.is_empty() => {
            let t: String = t
                .chars()
                .filter(|c| c.is_ascii_alphanumeric())
                .collect::<String>()
                .to_ascii_lowercase();
            let t = match t.as_str() {
                "boolean" => "bool".to_owned(),
                "integer" => "int".to_owned(),
                _ => t,
            };
            format!("ty-{t}")
        }
        _ => "ty-any".to_owned(),
    }
}

/// A rectangle's top, its two upper corners rounded by `rad`.
fn header_path(r: Rect, rad: f64) -> String {
    let (x, y, w, h) = (r.x, r.y, r.w, HEADER_H);
    format!(
        "M{} {}V{}A{rad} {rad} 0 0 1 {} {}H{}A{rad} {rad} 0 0 1 {} {}V{}Z",
        f(x),
        f(y + h),
        f(y + rad),
        f(x + rad),
        f(y),
        f(x + w - rad),
        f(x + w),
        f(y + rad),
        f(y + h),
    )
}

/// `text` cut with an ellipsis to fit `room` units.
fn fit(text: &str, room: f64) -> String {
    let max = (room / CHAR_W).floor().max(1.0) as usize;
    if text.chars().count() <= max {
        text.to_owned()
    } else {
        let cut: String = text.chars().take(max.saturating_sub(1)).collect();
        format!("{cut}…")
    }
}

fn f(v: f64) -> String {
    let r = (v * 10.0).round() / 10.0;
    if r == r.trunc() {
        format!("{}", r as i64)
    } else {
        format!("{r}")
    }
}

pub fn esc(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#39;"),
            _ => out.push(c),
        }
    }
    out
}
