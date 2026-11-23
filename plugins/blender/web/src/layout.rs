//! Where the nodes of a tree go (y down): like Blender's node drawing and
//! Blade's Node Editor, a header, a row per output (its socket on the
//! right edge), then a row per input (on the left edge); a column per step
//! from the nodes without inputs, as Blade places a tree built from text,
//! each node beside what feeds it. A frame wraps its nodes, its title
//! above them. The comments of the text are in boxes, as the Base Node
//! add-on draws them: over and under the nodes and frames they go with,
//! the graph's own in a corner, with room left for them.

use crate::graph::Tree;

pub const HEADER_H: f64 = 24.0;
pub const ROW_H: f64 = 22.0;
pub const BOTTOM_PAD: f64 = 8.0;
const MIN_W: f64 = 140.0;
const MAX_W: f64 = 260.0;
const COLUMN_GAP: f64 = 70.0;
const NODE_GAP: f64 = 24.0;
const FRAME_PAD: f64 = 16.0;
pub const FRAME_TITLE_H: f64 = 26.0;
/// The width of a character of the node font, about.
pub const CHAR_W: f64 = 6.6;
/// The boxes of comments: a line's height, the room around the text, the
/// gap to what they go with, the bar on their left, a character's width.
pub const NOTE_LINE: f64 = 14.0;
pub const NOTE_PAD: f64 = 5.0;
const NOTE_GAP: f64 = 6.0;
pub const NOTE_BAR: f64 = 2.0;
const NOTE_CHAR_W: f64 = 6.0;
/// The width of the comments of a frame, and of the graph's own.
const FRAME_NOTE_W: f64 = 300.0;
const CORNER_W: f64 = 360.0;

#[derive(Clone, Copy, Debug)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

pub struct Layout {
    pub nodes: Vec<Rect>,
    /// None for a frame without nodes.
    pub frames: Vec<Option<Rect>>,
    /// The boxes of comments.
    pub notes: Vec<Note>,
    pub bounds: Rect,
}

/// A box of comments: its lines, cut to its width.
pub struct Note {
    pub rect: Rect,
    pub lines: Vec<String>,
}

/// Comments cut at spaces to fit `width`; a longer word stays whole.
fn wrap(comments: &[String], width: f64) -> Vec<String> {
    let max = ((width - 2.0 * NOTE_PAD - NOTE_BAR) / NOTE_CHAR_W)
        .floor()
        .max(8.0) as usize;
    let mut out = Vec::new();
    for c in comments {
        let mut line = String::new();
        for word in c.split(' ') {
            if !line.is_empty() && line.chars().count() + 1 + word.chars().count() > max {
                out.push(std::mem::take(&mut line));
            } else if !line.is_empty() {
                line.push(' ');
            }
            line.push_str(word);
        }
        out.push(line);
    }
    out
}

/// A box of `lines` at (x, y), `w` wide; none for no line.
fn note(notes: &mut Vec<Note>, x: f64, y: f64, w: f64, lines: &[String]) {
    if !lines.is_empty() {
        notes.push(Note {
            rect: Rect {
                x,
                y,
                w,
                h: box_h(lines),
            },
            lines: lines.to_vec(),
        });
    }
}

/// The height of a box of `lines`, and the room it takes with its gap: 0 for none.
fn box_h(lines: &[String]) -> f64 {
    if lines.is_empty() {
        0.0
    } else {
        lines.len() as f64 * NOTE_LINE + 2.0 * NOTE_PAD
    }
}

fn room(lines: &[String]) -> f64 {
    let h = box_h(lines);
    if h > 0.0 {
        h + NOTE_GAP
    } else {
        0.0
    }
}

impl Layout {
    /// The center of output `o` of node `n`.
    pub fn output_at(&self, n: usize, o: usize) -> [f64; 2] {
        let r = self.nodes[n];
        [r.x + r.w, r.y + HEADER_H + ROW_H * o as f64 + ROW_H / 2.0]
    }

    /// The center of the row of setting `i` of node `n`.
    pub fn setting_at(&self, tree: &Tree, n: usize, i: usize) -> [f64; 2] {
        let r = self.nodes[n];
        let row = tree.nodes[n].outputs.len() + i;
        [r.x, r.y + HEADER_H + ROW_H * row as f64 + ROW_H / 2.0]
    }

    /// The center of input `i` of node `n`.
    pub fn input_at(&self, tree: &Tree, n: usize, i: usize) -> [f64; 2] {
        let r = self.nodes[n];
        let node = &tree.nodes[n];
        let row = node.outputs.len() + node.settings.len() + i;
        [r.x, r.y + HEADER_H + ROW_H * row as f64 + ROW_H / 2.0]
    }
}

pub fn layout(tree: &Tree) -> Layout {
    let count = tree.nodes.len();
    let sizes: Vec<(f64, f64)> = tree
        .nodes
        .iter()
        .map(|n| {
            let text = |s: &str| s.chars().count() as f64 * CHAR_W;
            let mut w = text(&n.title) + 30.0;
            for o in &n.outputs {
                w = w.max(text(&o.name) + 30.0);
            }
            for s in &n.settings {
                w = w.max(text(s) + 44.0);
            }
            for i in &n.inputs {
                let value = i.value.as_deref().map_or(0.0, |v| text(v) + 14.0);
                w = w.max(text(&i.name) + value + 34.0);
            }
            let rows = (n.outputs.len() + n.settings.len() + n.inputs.len()) as f64;
            (
                w.clamp(MIN_W, MAX_W).ceil(),
                HEADER_H + ROW_H * rows + BOTTOM_PAD,
            )
        })
        .collect();
    let above: Vec<Vec<String>> = (0..count)
        .map(|n| wrap(&tree.nodes[n].above, sizes[n].0))
        .collect();
    let below: Vec<Vec<String>> = (0..count)
        .map(|n| wrap(&tree.nodes[n].below, sizes[n].0))
        .collect();
    let frame_above: Vec<Vec<String>> = tree
        .frames
        .iter()
        .map(|f| wrap(&f.above, FRAME_NOTE_W))
        .collect();
    let frame_below: Vec<Vec<String>> = tree
        .frames
        .iter()
        .map(|f| wrap(&f.below, FRAME_NOTE_W))
        .collect();

    // How many links, at most, lead to each node; a cycle stops there.
    let mut depth = vec![0usize; count];
    for _ in 0..count {
        let mut changed = false;
        for (to, node) in tree.nodes.iter().enumerate() {
            for input in &node.inputs {
                if let Some((from, _)) = input.link {
                    if depth[to] < depth[from] + 1 {
                        depth[to] = depth[from] + 1;
                        changed = true;
                    }
                }
            }
        }
        if !changed {
            break;
        }
    }
    // Nodes feeding only later columns move right, next to what they feed.
    for _ in 0..count {
        let mut changed = false;
        // The Group Input, made first, stays in the first column.
        let first = usize::from(tree.nodes.first().is_some_and(|n| n.title == "Group Input"));
        for n in first..count {
            let users: Vec<usize> = (0..count)
                .filter(|&m| {
                    tree.nodes[m]
                        .inputs
                        .iter()
                        .any(|i| i.link.map(|l| l.0) == Some(n))
                })
                .collect();
            if let Some(min) = users.iter().map(|&m| depth[m]).min() {
                if min > depth[n] + 1 {
                    depth[n] = min - 1;
                    changed = true;
                }
            }
        }
        if !changed {
            break;
        }
    }
    let columns = depth.iter().copied().max().map_or(0, |d| d + 1);
    // The Group Output, made last, in the last column.
    if let Some(out) = count.checked_sub(1) {
        depth[out] = columns - 1;
    }

    let mut x_of = vec![0.0; columns];
    let mut x = 0.0;
    for (c, slot) in x_of.iter_mut().enumerate() {
        *slot = x;
        let w = (0..count)
            .filter(|&n| depth[n] == c)
            .map(|n| sizes[n].0)
            .fold(0.0, f64::max);
        x += w + COLUMN_GAP;
    }

    // The frames around each frame (itself first) and each node (the innermost first).
    let frame_count = tree.frames.len();
    let frame_chain: Vec<Vec<usize>> = (0..frame_count)
        .map(|f| {
            let mut c = vec![f];
            while let Some(p) = tree.frames[*c.last().expect("a frame")].parent {
                if c.contains(&p) {
                    break;
                }
                c.push(p);
            }
            c
        })
        .collect();
    let chain: Vec<Vec<usize>> = (0..count)
        .map(|n| {
            tree.nodes[n]
                .frame
                .map_or_else(Vec::new, |f| frame_chain[f].clone())
        })
        .collect();
    let mut inner_first: Vec<usize> = (0..frame_count).collect();
    inner_first.sort_by_key(|&f| std::cmp::Reverse(frame_chain[f].len()));

    let mut rects = vec![
        Rect {
            x: 0.0,
            y: 0.0,
            w: 0.0,
            h: 0.0
        };
        count
    ];
    for (c, &column_x) in x_of.iter().enumerate() {
        let mut column: Vec<usize> = (0..count).filter(|&n| depth[n] == c).collect();
        // Each node beside the middle of what feeds it.
        let wanted: Vec<(usize, f64)> = column
            .iter()
            .map(|&n| {
                let ys: Vec<f64> = tree.nodes[n]
                    .inputs
                    .iter()
                    .filter_map(|i| i.link)
                    .filter(|(from, _)| depth[*from] < c)
                    .map(|(from, o)| rects[from].y + HEADER_H + ROW_H * o as f64)
                    .collect();
                let y = if ys.is_empty() {
                    f64::NAN
                } else {
                    ys.iter().sum::<f64>() / ys.len() as f64 - HEADER_H
                };
                (n, y)
            })
            .collect();
        if c > 0 {
            column.sort_by(|a, b| {
                let ya = wanted.iter().find(|w| w.0 == *a).map_or(0.0, |w| w.1);
                let yb = wanted.iter().find(|w| w.0 == *b).map_or(0.0, |w| w.1);
                let ya = if ya.is_nan() { f64::MAX } else { ya };
                let yb = if yb.is_nan() { f64::MAX } else { yb };
                ya.partial_cmp(&yb)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then(a.cmp(b))
            });
        }
        let mut next = 0.0f64;
        let mut prev: &[usize] = &[];
        for n in column {
            let want = wanted.iter().find(|w| w.0 == n).map_or(f64::NAN, |w| w.1);
            // Room for its comments, and for the frames it leaves or enters.
            let mut top = next + room(&above[n]);
            for &f in prev.iter().filter(|f| !chain[n].contains(f)) {
                top += FRAME_PAD + room(&frame_below[f]);
            }
            for &f in chain[n].iter().filter(|f| !prev.contains(f)) {
                top += FRAME_TITLE_H + room(&frame_above[f]);
            }
            let y = if want.is_nan() { top } else { want.max(top) };
            let (w, h) = sizes[n];
            rects[n] = Rect {
                x: column_x,
                y,
                w,
                h,
            };
            next = y + h + room(&below[n]) + NODE_GAP;
            prev = &chain[n];
        }
    }

    // A node with the room of its comments.
    let whole = |n: usize, r: &Rect| {
        let up = room(&above[n]);
        Rect {
            y: r.y - up,
            h: r.h + up + room(&below[n]),
            ..*r
        }
    };
    // The frames, the inner ones first: each wraps its nodes and frames, its title over them.
    let frames_of = |rects: &[Rect]| {
        let mut out: Vec<Option<Rect>> = vec![None; frame_count];
        for &f in &inner_first {
            let Some(r) = cover(
                (0..count)
                    .filter(|&n| chain[n].first() == Some(&f))
                    .map(|n| whole(n, &rects[n]))
                    .chain(
                        (0..frame_count)
                            .filter(|&g| tree.frames[g].parent == Some(f))
                            .filter_map(|g| {
                                out[g].map(|r| Rect {
                                    h: r.h + room(&frame_below[g]),
                                    ..r
                                })
                            }),
                    ),
            ) else {
                continue;
            };
            let up = room(&frame_above[f]);
            let w = if up > 0.0 {
                (r.w + 2.0 * FRAME_PAD).max(FRAME_NOTE_W + 2.0 * FRAME_PAD)
            } else {
                r.w + 2.0 * FRAME_PAD
            };
            out[f] = Some(Rect {
                x: r.x - FRAME_PAD,
                y: r.y - FRAME_TITLE_H - up,
                w,
                h: r.h + FRAME_TITLE_H + up + FRAME_PAD,
            });
        }
        out
    };
    // Nothing covers a frame, its title above all, but what it holds: what
    // overlaps it moves down, or the frame does when it is lower. Each pass moves one thing:
    // a graph of many frames, as the game art showcase, needs a couple of hundred.
    let chain = &chain;
    let members =
        |f: usize| -> Vec<usize> { (0..count).filter(|&n| chain[n].contains(&f)).collect() };
    for _ in 0..1024 {
        let frames = frames_of(&rects);
        let mut push: Option<(Vec<usize>, f64)> = None;
        'search: for f in 0..frame_count {
            let Some(fr) = frames[f] else { continue };
            for m in (0..count).filter(|&m| !chain[m].contains(&f)) {
                let w = whole(m, &rects[m]);
                if !overlaps(&w, &fr) {
                    continue;
                }
                push = Some(if w.y + w.h / 2.0 < fr.y + fr.h / 2.0 {
                    (members(f), w.y + w.h + NODE_GAP - fr.y)
                } else {
                    // The node moves with the outermost frame of its own that is not around f.
                    let own = chain[m]
                        .iter()
                        .rev()
                        .find(|&&g| !frame_chain[f].contains(&g));
                    let moved = own.map_or(vec![m], |&g| members(g));
                    let top = own.and_then(|&g| frames[g]).map_or(w.y, |r| r.y);
                    (moved, fr.y + fr.h + NODE_GAP - top)
                });
                break 'search;
            }
            for g in 0..frame_count {
                if g == f || frame_chain[g].contains(&f) || frame_chain[f].contains(&g) {
                    continue;
                }
                let Some(gr) = frames[g] else { continue };
                if overlaps(&fr, &gr) {
                    let (upper, lower, lr) = if gr.y >= fr.y {
                        (fr, g, gr)
                    } else {
                        (gr, f, fr)
                    };
                    push = Some((members(lower), upper.y + upper.h + NODE_GAP - lr.y));
                    break 'search;
                }
            }
        }
        let Some((moved, dy)) = push else { break };
        for n in moved {
            rects[n].y += dy.max(1.0);
        }
        // Then no node of a column covers the next one.
        for c in 0..columns {
            let mut column: Vec<usize> = (0..count).filter(|&n| depth[n] == c).collect();
            column.sort_by(|a, b| rects[*a].y.total_cmp(&rects[*b].y));
            for pair in column.windows(2) {
                let (a, b) = (
                    whole(pair[0], &rects[pair[0]]),
                    whole(pair[1], &rects[pair[1]]),
                );
                let under = a.y + a.h + NODE_GAP;
                if b.y < under {
                    rects[pair[1]].y += under - b.y;
                }
            }
        }
    }

    let frames = frames_of(&rects);
    let mut notes = Vec::new();
    for (n, r) in rects.iter().enumerate() {
        note(&mut notes, r.x, r.y - room(&above[n]), r.w, &above[n]);
        note(&mut notes, r.x, r.y + r.h + NOTE_GAP, r.w, &below[n]);
    }
    for (f, rect) in frames.iter().enumerate() {
        let Some(rect) = rect else { continue };
        note(
            &mut notes,
            rect.x + FRAME_PAD,
            rect.y + FRAME_TITLE_H,
            FRAME_NOTE_W,
            &frame_above[f],
        );
        note(
            &mut notes,
            rect.x,
            rect.y + rect.h + NOTE_GAP,
            FRAME_NOTE_W,
            &frame_below[f],
        );
    }
    let whole: Vec<Rect> = rects.iter().enumerate().map(|(n, r)| whole(n, r)).collect();
    let drawn = |notes: &[Note]| {
        cover(
            whole
                .iter()
                .copied()
                .chain(frames.iter().flatten().copied())
                .chain(notes.iter().map(|n| n.rect)),
        )
    };
    // The graph's own comments, in the corner over it.
    let corner = wrap(&tree.notes, CORNER_W);
    if let Some(b) = drawn(&notes).filter(|_| !corner.is_empty()) {
        note(
            &mut notes,
            b.x,
            b.y - room(&corner) - NOTE_GAP,
            CORNER_W,
            &corner,
        );
    } else {
        note(&mut notes, 0.0, 0.0, CORNER_W, &corner);
    }
    let bounds = drawn(&notes).unwrap_or(Rect {
        x: 0.0,
        y: 0.0,
        w: 200.0,
        h: 100.0,
    });
    Layout {
        nodes: rects,
        frames,
        notes,
        bounds,
    }
}

fn overlaps(a: &Rect, b: &Rect) -> bool {
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
}

fn cover(rects: impl Iterator<Item = Rect>) -> Option<Rect> {
    rects
        .map(|r| [r.x, r.y, r.x + r.w, r.y + r.h])
        .reduce(|a, b| {
            [
                a[0].min(b[0]),
                a[1].min(b[1]),
                a[2].max(b[2]),
                a[3].max(b[3]),
            ]
        })
        .map(|[x0, y0, x1, y1]| Rect {
            x: x0,
            y: y0,
            w: x1 - x0,
            h: y1 - y0,
        })
}
