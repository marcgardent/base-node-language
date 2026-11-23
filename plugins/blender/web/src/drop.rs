//! What the text gives when it is dragged out of the page as a `.bn` file:
//! its file name, and what its head offers the host it is dropped on (the
//! Blender add-on reads the same head, `base_node_blender::header`).

use base_node::{ast::key, File};
use base_node_blender::header_of;
use serde::Serialize;

use crate::Problem;

#[derive(Serialize, Debug)]
pub(crate) struct Drop {
    /// `<@module>.bn`, else the file of its last graph.
    file: String,
    title: Option<String>,
    author: Option<String>,
    license: Option<String>,
    /// What a host may do with it: `library`, `groups`, `example`, `modifier`.
    offer: Vec<String>,
    example: Option<String>,
    modifier: Option<String>,
    /// Why the head is refused: a host then does nothing with the file.
    problems: Vec<Problem>,
    /// The Blender add-on reads the file (its graphs are of Blender's tree
    /// kinds): what it offers is said only then.
    blender: bool,
}

impl Drop {
    #[cfg(test)]
    pub(crate) fn blender_reads(&self) -> bool {
        self.blender
    }
}

pub(crate) fn drop(source: &str, file: &File, blender: bool) -> Drop {
    let fallback = file
        .graphs
        .last()
        .map_or_else(|| "graph".to_owned(), |g| key(&g.name));
    match header_of(source, "view.bn", file) {
        Ok(h) => Drop {
            file: format!("{}.bn", h.module.as_deref().unwrap_or(&fallback)),
            title: h.title,
            author: h.author,
            license: h.license,
            offer: h.offer,
            example: h.example,
            modifier: h.modifier,
            problems: Vec::new(),
            blender,
        },
        Err(e) => Drop {
            file: format!("{fallback}.bn"),
            title: None,
            author: None,
            license: None,
            offer: Vec::new(),
            example: None,
            modifier: None,
            problems: e.diagnostics.iter().map(Problem::of).collect(),
            blender,
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn of(src: &str) -> Drop {
        drop(src, &base_node::parse(src, "t.bn").unwrap(), true)
    }

    #[test]
    fn the_drop_example_offers_everything() {
        let src = std::fs::read_to_string("../examples/drop_example.bn").unwrap();
        let d = of(&src);
        assert_eq!(d.file, "drop_example.bn");
        assert_eq!(d.title.as_deref(), Some("Ripples and waves"));
        assert_eq!(d.offer, ["library", "groups", "example", "modifier"]);
        assert!(d.problems.is_empty());
    }

    #[test]
    fn a_file_without_module_is_named_after_its_last_graph() {
        let d = of("geometry graph \"my field\"() -> Geometry {\n  return Grid()\n}\n");
        assert_eq!(d.file, "my_field.bn");
        assert_eq!(d.offer, ["groups", "example"]);
    }

    #[test]
    fn a_head_in_error_offers_nothing() {
        let d = of("// @offer library\ngeometry graph g() -> Geometry {\n  return Grid()\n}\n");
        assert!(d.offer.is_empty());
        assert_eq!(d.problems[0].line, 1);
    }
}
