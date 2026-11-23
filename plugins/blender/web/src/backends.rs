//! Which backends run a text: the Blender add-on Base Node (a tag per
//! tree kind of the text, `blender-geometry`, `blender-shader` or
//! `blender-compositor`: its graphs of that kind within the target `blender`,
//! which checks each against the nodes of its kind of tree; none of another
//! kind. The ids are the tags', a host and a tree, not targets), and the
//! targets it fits (spec/targets.md). What is checked is
//! what base-node-blender knows: a graph's kind, its nodes; a host may still
//! refuse a socket it does not have. A graph that calls a graph of a stdlib
//! module the text uses brings that graph's issues (the stdlib is
//! base-node-blender's, built in); a module outside the stdlib is not read.

use base_node::File;
use base_node_blender::{check_target, infer};
use serde::Serialize;

#[derive(Serialize, Debug)]
pub struct Backend {
    id: &'static str,
    host: &'static str,
    label: &'static str,
    ok: bool,
    /// Why it does not run there; empty when it does.
    why: String,
}

impl Backend {
    /// It is one of `host`'s and runs the text.
    pub(crate) fn runs_on(&self, host: &str) -> bool {
        self.ok && self.host == host
    }
}

pub fn backends(file: &File) -> Vec<Backend> {
    const BLENDER: [(&str, &str, &str); 3] = [
        ("geometry", "blender-geometry", "Geometry Nodes"),
        ("shader", "blender-shader", "Shader"),
        ("compositor", "blender-compositor", "Compositor"),
    ];
    let mut kinds: Vec<&str> = Vec::new();
    for g in &file.graphs {
        if !kinds.contains(&g.kind.as_str()) {
            kinds.push(&g.kind);
        }
    }
    let foreign = |known: &[&str]| {
        kinds
            .iter()
            .find(|k| !known.contains(k))
            .map(|k| format!("a `{k} graph` is not one of its trees"))
    };
    let mut out = Vec::new();

    // The add-on reads each graph as a tree of its kind.
    let blender_kinds: Vec<&str> = BLENDER.iter().map(|b| b.0).collect();
    let present: Vec<_> = BLENDER.iter().filter(|b| kinds.contains(&b.0)).collect();
    if present.is_empty() {
        let why = foreign(&blender_kinds).unwrap_or_else(|| "no graph".to_owned());
        out.push(backend("blender", "Blender", "Nodes", Some(why)));
    }
    for (kind, id, label) in present {
        let why = foreign(&blender_kinds).or_else(|| first_error(&only(file, kind), "blender"));
        out.push(backend(id, "Blender", label, why));
    }

    out
}

/// `file` with its graphs of `kind` only.
fn only(file: &File, kind: &str) -> File {
    File {
        uses: file.uses.clone(),
        graphs: file
            .graphs
            .iter()
            .filter(|g| g.kind == kind)
            .cloned()
            .collect(),
    }
}

/// A target the text fits: as it is, or through its translator from another (`from`).
#[derive(Serialize, Debug, PartialEq, Eq)]
pub struct Fit {
    name: String,
    from: Option<String>,
}

/// The targets the text fits, those it fits as it is first.
pub fn targets(file: &File) -> Vec<Fit> {
    let mut fits: Vec<Fit> = infer(file)
        .fits
        .into_iter()
        .map(|(name, from)| Fit { name, from })
        .collect();
    fits.sort_by_key(|f| f.from.is_some());
    fits
}

fn first_error(file: &File, target: &str) -> Option<String> {
    let errors = check_target(file, target).expect("a target of base-node");
    let first = errors.first()?;
    Some(match errors.len() {
        1 => first.to_string(),
        n => format!("{first} (+{} more)", n - 1),
    })
}

fn backend(
    id: &'static str,
    host: &'static str,
    label: &'static str,
    why: Option<String>,
) -> Backend {
    Backend {
        id,
        host,
        label,
        ok: why.is_none(),
        why: why.unwrap_or_default(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tags(src: &str) -> Vec<(&'static str, bool)> {
        backends(&base_node::parse(src, "t.bn").unwrap())
            .into_iter()
            .map(|b| (b.id, b.ok))
            .collect()
    }

    #[test]
    fn a_geometry_graph_runs_in_blender_only() {
        let t = tags("geometry graph g() -> Geometry {\n  return Cube()\n}\n");
        assert_eq!(t, [("blender-geometry", true)]);
    }

    #[test]
    fn shader_and_geometry_graphs_run_in_blender_together() {
        let t = tags(
            "shader graph s() -> Shader {\n  return Emission()\n}\ngeometry graph g() -> Geometry {\n  return Cube()\n}\n",
        );
        assert_eq!(t, [("blender-geometry", true), ("blender-shader", true)]);
    }

    #[test]
    fn a_graph_of_another_kind_runs_in_no_tree_of_blender() {
        let t = tags("pixel graph g(x: Float) -> Float {\n  return x * 2.0\n}\n");
        assert_eq!(t, [("blender", false)]);
    }

    #[test]
    fn a_node_blender_does_not_have_is_refused() {
        let t = tags("geometry graph g() -> Geometry {\n  return MeshCube()\n}\n");
        assert_eq!(t, [("blender-geometry", false)]);
    }

    #[test]
    fn the_targets_a_math_text_fits() {
        let f = base_node::parse(
            "geometry graph g(x: Float) -> Float {\n  return x * 2.0\n}\n",
            "t.bn",
        )
        .unwrap();
        let names: Vec<String> = targets(&f).into_iter().map(|f| f.name).collect();
        assert_eq!(names, ["blender"]);
        // A shader graph of math fits the shader variants too
        let shader = "shader graph g(x: Float) -> Float {\n  return x * 2.0\n}\n";
        assert_eq!(
            fits(shader)[..3],
            ["blender", "blender cycles", "blender eevee"]
        );
    }

    fn fits(src: &str) -> Vec<String> {
        targets(&base_node::parse(src, "t.bn").unwrap())
            .into_iter()
            .map(|f| f.name)
            .collect()
    }

    #[test]
    fn a_call_of_a_compositor_module_does_not_fit_geometry() {
        let geometry = "use merge (with_alpha)\ngeometry graph g(c: Color) -> Color {\n  return with_alpha(c, 0.5)\n}\n";
        assert_eq!(tags(geometry), [("blender-geometry", false)]);
        let names = fits(geometry);
        assert!(!names.contains(&"blender".to_owned()), "{names:?}");
        assert!(
            fits(&geometry.replace("geometry graph", "compositor graph"))
                .contains(&"blender".to_owned())
        );
        let compositor = "use merge (with_alpha)\ncompositor graph g(c: Color) -> Color {\n  return with_alpha(c, 0.5)\n}\n";
        assert_eq!(tags(compositor), [("blender-compositor", true)]);
    }

    #[test]
    fn a_call_of_a_math_module_fits_every_blender_tree() {
        let t = tags(
            "use math (bias)\ngeometry graph g(x: Float) -> Float {\n  return bias(x)\n}\nshader graph s(x: Float) -> Float {\n  return bias(x)\n}\ncompositor graph c(x: Float) -> Float {\n  return bias(x)\n}\n",
        );
        assert_eq!(
            t,
            [
                ("blender-geometry", true),
                ("blender-shader", true),
                ("blender-compositor", true)
            ]
        );
        let names =
            fits("use math (bias)\ngeometry graph g(x: Float) -> Float {\n  return bias(x)\n}\n");
        assert_eq!(names, ["blender"]);
    }

    #[test]
    fn a_module_outside_the_stdlib_is_not_followed() {
        let t = tags("use mine (f)\ngeometry graph g(x: Float) -> Float {\n  return f(x)\n}\n");
        assert_eq!(t, [("blender-geometry", true)]);
    }
}
