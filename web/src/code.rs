//! A `.bn` text as highlighted HTML, a `<span class="line">` per line,
//! from base-node's tokens (comments kept): keywords, node calls, types,
//! numbers and colors, strings, comments. A text that does not tokenize
//! is shown plain.

use base_node::{tokenize, TokenKind};

use crate::svg::esc;

pub fn highlight(source: &str) -> String {
    let lines: Vec<Vec<char>> = source.lines().map(|l| l.chars().collect()).collect();
    let mut classes: Vec<Vec<Option<&'static str>>> =
        lines.iter().map(|l| vec![None; l.len()]).collect();
    if let Ok(tokens) = tokenize(source, "view.bn", false) {
        let next_code = |i: usize| {
            tokens[i + 1..]
                .iter()
                .find(|t| !matches!(t.kind, TokenKind::Comment))
        };
        for (i, t) in tokens.iter().enumerate() {
            let class = match &t.kind {
                TokenKind::Keyword => Some("k"),
                TokenKind::Number | TokenKind::Color => Some("n"),
                TokenKind::String | TokenKind::OpenString => Some("s"),
                TokenKind::Comment => Some("c"),
                TokenKind::Ident => {
                    let next = next_code(i);
                    if next.is_some_and(|n| n.is("(") || n.is("[")) {
                        Some("f")
                    } else if next.is_some_and(|n| n.text == "graph") {
                        Some("k")
                    } else if t.text.chars().next().is_some_and(char::is_uppercase) {
                        Some("t")
                    } else {
                        None
                    }
                }
                TokenKind::Punct(_) => Some("p"),
                TokenKind::Eof => None,
            };
            let Some(class) = class else { continue };
            // A token may span lines (a string): mark from its start on.
            let (mut line, mut col) = (t.line.saturating_sub(1), t.col.saturating_sub(1));
            for _ in t.text.chars() {
                if line >= classes.len() {
                    break;
                }
                if col >= classes[line].len() {
                    line += 1;
                    col = 0;
                    continue;
                }
                classes[line][col] = Some(class);
                col += 1;
            }
        }
    }
    let mut html = String::new();
    for (n, (line, marks)) in lines.iter().zip(&classes).enumerate() {
        html.push_str(&format!(r#"<span class="line" data-line="{}">"#, n + 1));
        let mut i = 0;
        while i < line.len() {
            let class = marks[i];
            let start = i;
            while i < line.len() && marks[i] == class {
                i += 1;
            }
            let text: String = line[start..i].iter().collect();
            match class {
                Some(c) => html.push_str(&format!(r#"<span class="{c}">{}</span>"#, esc(&text))),
                None => html.push_str(&esc(&text)),
            }
        }
        html.push_str("</span>");
    }
    html
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn calls_keywords_and_comments() {
        let html =
            highlight("// hi\ngeometry graph g() -> Geometry {\n  return MeshCube(size: 1.0)\n}\n");
        assert!(html.contains(r#"<span class="c">// hi</span>"#));
        assert!(html.contains(r#"<span class="k">geometry</span>"#));
        assert!(html.contains(r#"<span class="f">MeshCube</span>"#));
        assert!(html.contains(r#"<span class="t">Geometry</span>"#));
        assert!(html.contains(r#"<span class="n">1.0</span>"#));
        assert_eq!(html.matches(r#"class="line""#).count(), 4);
    }

    #[test]
    fn markup_is_escaped() {
        assert!(highlight("x < y").contains("&lt;"));
    }
}
