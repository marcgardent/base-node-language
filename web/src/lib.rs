//! A `.bn` text for the browser, read-only: its highlighted code, a node
//! graph per graph of the text (SVG), the backends it runs on, and what it
//! offers as a `.bn` file dragged on a host. Compiled to
//! wasm for the `<bn-view>` Web Component (`web/bn-view.js`).

mod backends;
mod code;
mod drop;
mod graph;
mod layout;
mod notes;
mod sugar;
mod svg;

use backends::Backend;
use serde::Serialize;
use wasm_bindgen::prelude::wasm_bindgen;

#[derive(Serialize, Debug)]
struct View {
    /// The text, highlighted: a `<span class="line">` per line.
    code: String,
    /// Why the text does not parse; none when it does.
    error: Option<Problem>,
    graphs: Vec<GraphView>,
    backends: Vec<Backend>,
    /// The targets the text fits (`blender`, `blender gltf`…), translated ones last.
    targets: Vec<backends::Fit>,
    /// The text as a `.bn` file to drag on a host; none when it does not parse.
    drop: Option<drop::Drop>,
}

#[derive(Serialize, Debug)]
struct Problem {
    line: usize,
    col: usize,
    message: String,
}

impl Problem {
    fn of(d: &base_node::Diagnostic) -> Self {
        Self {
            line: d.line,
            col: d.col,
            message: d.message.clone(),
        }
    }
}

#[derive(Serialize, Debug)]
struct GraphView {
    name: String,
    kind: String,
    description: Option<String>,
    svg: String,
    nodes: usize,
}

fn view(source: &str) -> View {
    let code = code::highlight(source);
    match base_node::parse(source, "view.bn") {
        Ok(file) => {
            let backends = backends::backends(&file);
            let mut trees = graph::trees(&file);
            notes::attach(&mut trees, source);
            View {
                code,
                error: None,
                graphs: trees
                    .iter()
                    .map(|t| GraphView {
                        name: t.name.clone(),
                        kind: t.kind.clone(),
                        description: t.description.clone(),
                        svg: svg::svg(t),
                        nodes: t.nodes.len(),
                    })
                    .collect(),
                drop: Some(drop_of(source, &file, &backends)),
                backends,
                targets: backends::targets(&file),
            }
        }
        Err(e) => View {
            code,
            error: Some(parse_problem(&e)),
            graphs: Vec::new(),
            backends: Vec::new(),
            targets: Vec::new(),
            drop: None,
        },
    }
}

/// The view of `source`, as JSON.
#[wasm_bindgen]
pub fn render(source: &str) -> String {
    serde_json::to_string(&view(source)).unwrap_or_else(|_| "{}".to_owned())
}

/// What `source` gives as a `.bn` file dragged on a host, alone (no code,
/// no graph), as JSON: `{"drop": …}`, or `{"error": …}` when it does not
/// parse.
#[wasm_bindgen]
pub fn file(source: &str) -> String {
    serde_json::to_string(&file_view(source)).unwrap_or_else(|_| "{}".to_owned())
}

#[derive(Serialize, Debug)]
struct FileView {
    error: Option<Problem>,
    drop: Option<drop::Drop>,
}

fn file_view(source: &str) -> FileView {
    match base_node::parse(source, "view.bn") {
        Ok(file) => FileView {
            error: None,
            drop: Some(drop_of(source, &file, &backends::backends(&file))),
        },
        Err(e) => FileView {
            error: Some(parse_problem(&e)),
            drop: None,
        },
    }
}

/// The text as a file, offering what it offers only if the Blender add-on
/// reads it.
fn drop_of(source: &str, file: &base_node::File, backends: &[Backend]) -> drop::Drop {
    let blender = backends.iter().any(|b| b.runs_on("Blender"));
    drop::drop(source, file, blender)
}

/// The first reason a text does not parse.
fn parse_problem(e: &base_node::BnError) -> Problem {
    e.diagnostics.first().map_or_else(
        || Problem {
            line: 0,
            col: 0,
            message: "cannot parse".to_owned(),
        },
        Problem::of,
    )
}

/// The version of base-node it reads.
#[wasm_bindgen]
pub fn version() -> String {
    base_node::VERSION.to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_example_and_stdlib_module_renders() {
        let root = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
        let mut seen = 0;
        for dir in ["examples", "stdlib"] {
            let Ok(entries) = std::fs::read_dir(format!("{root}/{dir}")) else {
                continue;
            };
            for e in entries.flatten() {
                let p = e.path();
                if p.extension().is_some_and(|x| x == "bn") {
                    let src = std::fs::read_to_string(&p).unwrap();
                    let v = view(&src);
                    assert!(v.error.is_none(), "{}: {:?}", p.display(), v.error);
                    assert!(!v.graphs.is_empty(), "{}", p.display());
                    assert!(v.graphs.iter().all(|g| g.svg.starts_with("<svg")));
                    seen += 1;
                }
            }
        }
        assert!(seen > 3);
    }

    #[test]
    fn only_a_text_blender_reads_offers_it_anything() {
        let pixel = view("pixel graph g(x: Float) -> Float {\n  return x\n}\n");
        assert!(!pixel.drop.unwrap().blender_reads());
        let geometry = view("geometry graph g() -> Geometry {\n  return Grid()\n}\n");
        assert!(geometry.drop.unwrap().blender_reads());
    }

    #[test]
    fn a_file_alone_gives_its_head() {
        let src = std::fs::read_to_string("../examples/drop_example.bn").unwrap();
        let f = file_view(&src);
        assert!(f.error.is_none());
        assert!(f.drop.unwrap().blender_reads());
        assert!(file_view("geometry graph (").error.is_some());
    }

    #[test]
    fn a_parse_error_keeps_the_code() {
        let v = view("geometry graph g( {\n");
        assert!(v.error.is_some());
        assert!(v.code.contains("geometry"));
    }
}
