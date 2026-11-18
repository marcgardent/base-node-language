//! The comments of a text, on the nodes they go with, as the Base Node
//! add-on shows them in Blender's Node Editor (`host/comments.py`):
//!
//! - alone on its lines, a comment goes with what follows it: over the node
//!   of the next statement, over a frame for the head of its block, under a
//!   frame (or a zone's output) for the end of its block;
//! - after code, with the statement (or the block's end) of that line;
//! - before a graph, after its last statement, or after the last graph: with
//!   the graph itself, in a corner of the editor; the file's head (a blank
//!   line away from what follows it) goes with the last graph, the one a
//!   text stands for.
//!
//! A statement that makes no node of its own (`b = a`) passes its comments
//! to the next place.

use base_node::TokenKind;

use crate::graph::{Holder, Tree};

/// A place of the text: (line, a block's end, (tree, holder)).
type At = (usize, bool, Option<(usize, Holder)>);

/// Where a comment goes: (tree, holder, under it).
type Slot = (usize, Holder, bool);

pub fn attach(trees: &mut [Tree], source: &str) {
    let Some(last) = trees.len().checked_sub(1) else {
        return;
    };
    let Ok(tokens) = base_node::tokenize(source, "view.bn", false) else {
        return;
    };
    let rows: Vec<&str> = source.split('\n').collect();
    // Every place of every graph, in the text's order.
    let mut places: Vec<At> = trees
        .iter()
        .enumerate()
        .flat_map(|(t, tree)| {
            tree.places
                .iter()
                .map(move |p| (p.line, p.close, p.holder.map(|h| (t, h))))
        })
        .collect();
    places.sort_by_key(|p| p.0);
    let first = places.first().map_or(usize::MAX, |p| p.0);

    let comments: Vec<(usize, bool, String)> = tokens
        .iter()
        .filter(|t| t.kind == TokenKind::Comment)
        .map(|c| {
            let row = rows.get(c.line - 1).copied().unwrap_or("");
            let before: String = row.chars().take(c.col.saturating_sub(1)).collect();
            (c.line, before.trim().is_empty(), plain(&c.text))
        })
        .collect();
    // The file's head: the comments at its top, a blank line before what follows.
    let lead: Vec<usize> = comments
        .iter()
        .filter(|c| c.1 && c.0 < first)
        .map(|c| c.0)
        .collect();
    let head_end = lead.last().copied().filter(|&l| {
        (l..first.saturating_sub(1)).any(|r| rows.get(r).is_some_and(|s| s.trim().is_empty()))
    });

    let mut carried: Vec<String> = Vec::new();
    let mut found: Vec<(Slot, String)> = Vec::new();
    for (line, alone, text) in comments {
        if head_end.is_some_and(|h| line <= h) {
            found.push(((last, Holder::Tree, false), text));
            continue;
        }
        let at = if alone {
            places.iter().position(|p| p.0 > line)
        } else {
            places
                .iter()
                .position(|p| p.0 == line && !p.1)
                .or_else(|| places.iter().position(|p| p.0 == line))
                .or_else(|| places.iter().rposition(|p| p.0 < line))
        };
        let slot = at.and_then(|i| {
            // A place without a node passes its comments on to the next one with one.
            places[i..]
                .iter()
                .find_map(|p| p.2.map(|(t, h)| (t, h, p.1)))
        });
        match slot {
            Some(s) => found.push((s, text)),
            None => carried.push(text),
        }
    }
    for text in carried {
        found.push(((last, Holder::Tree, true), text));
    }
    for ((t, holder, under), text) in found {
        let tree = &mut trees[t];
        let into = match holder {
            Holder::Tree => &mut tree.notes,
            Holder::Node(n) if under => &mut tree.nodes[n].below,
            Holder::Node(n) => &mut tree.nodes[n].above,
            Holder::Frame(f) if under => &mut tree.frames[f].below,
            Holder::Frame(f) => &mut tree.frames[f].above,
        };
        into.push(text);
    }
}

/// A comment's text without its `//`.
fn plain(text: &str) -> String {
    let t = text.trim_end();
    let t = t.strip_prefix("//").unwrap_or(t);
    t.strip_prefix(' ').unwrap_or(t).to_owned()
}

#[cfg(test)]
mod tests {
    use crate::graph::trees;

    fn built(src: &str) -> Vec<crate::graph::Tree> {
        let mut t = trees(&base_node::parse(src, "t.bn").expect("parses"));
        super::attach(&mut t, src);
        t
    }

    #[test]
    fn comments_go_with_what_they_comment() {
        let src = "// @title Waves\n// A head, a blank line away\n\n\
                   // the graph\n\
                   geometry graph g(h: Float) -> Geometry {\n  \
                     // a grid to move\n  \
                     grid = Grid(size_x: h)  // its size\n  \
                     \"Move\" {\n    \
                       // up\n    \
                       moved = SetPosition(geometry: grid)\n    \
                       // the frame's end\n  \
                     }\n  \
                     // the result\n  \
                     return moved\n\
                   }\n\
                   // after all\n";
        let t = &built(src)[0];
        let node = |title: &str| t.nodes.iter().find(|n| n.title == title).expect(title);
        assert_eq!(node("Grid").above, ["a grid to move", "its size"]);
        assert_eq!(node("Set Position").above, ["up"]);
        assert_eq!(t.frames[0].below, ["the frame's end"]);
        assert_eq!(node("Group Output").above, ["the result"]);
        assert_eq!(
            t.notes,
            [
                "@title Waves",
                "A head, a blank line away",
                "the graph",
                "after all"
            ]
        );
    }

    #[test]
    fn a_statement_without_a_node_passes_its_comments_on() {
        let src = "geometry graph g(h: Float) -> Float {\n  // an alias\n  a = h\n  \
                   b = a * 2.0\n  return b\n}\n";
        let t = &built(src)[0];
        let math = t
            .nodes
            .iter()
            .find(|n| n.title == "Multiply")
            .expect("a Multiply");
        assert_eq!(math.above, ["an alias"]);
    }

    #[test]
    fn nothing_covers_a_frame_but_what_it_holds() {
        let root = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
        for dir in ["examples", "stdlib"] {
            for e in std::fs::read_dir(format!("{root}/{dir}"))
                .unwrap()
                .flatten()
            {
                let p = e.path();
                if p.extension().is_none_or(|x| x != "bn") {
                    continue;
                }
                let src = std::fs::read_to_string(&p).unwrap();
                for t in built(&src) {
                    let l = crate::layout::layout(&t);
                    for (f, fr) in l.frames.iter().enumerate() {
                        let Some(fr) = fr else { continue };
                        for (n, r) in l.nodes.iter().enumerate() {
                            let mut inside = t.nodes[n].frame;
                            let mut held = false;
                            while let Some(g) = inside {
                                held |= g == f;
                                inside = t.frames[g].parent.filter(|&p| p != g);
                                if held {
                                    break;
                                }
                            }
                            let hit = r.x < fr.x + fr.w
                                && fr.x < r.x + r.w
                                && r.y < fr.y + fr.h
                                && fr.y < r.y + r.h;
                            assert!(
                                held || !hit,
                                "{}: {} covers frame {}",
                                p.display(),
                                t.nodes[n].title,
                                t.frames[f].label
                            );
                        }
                    }
                }
            }
        }
    }
}
