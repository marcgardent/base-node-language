//! The zones of Blender, written as calls with a body: their shape is this library's to say
//! (python/tests/test_zones.py, test_repeat.py: the same messages).

use base_node::ast::{AssignValue, Stmt};
use base_node::parse;
use base_node_blender::zones::{refused, word};

fn first(body: &str) -> AssignValue {
    let src =
        format!("geometry graph g(geometry: Geometry, t: Float) -> Geometry {{\n{body}\n}}\n");
    let file = parse(&src, "t.bn").unwrap();
    match &file.graphs[0].body[0] {
        Stmt::Assign(a) => a.value.clone(),
        _ => panic!("an assignment first"),
    }
}

fn said(body: &str) -> Option<(usize, usize, String)> {
    match first(body) {
        AssignValue::BodyCall(c) => refused(&c),
        _ => panic!("a call with a body"),
    }
}

#[test]
fn the_calls_that_take_a_body_are_the_zones() {
    for (body, zone) in [
        (
            "  r = repeat(3, s: 0.0) -> {\n    return s\n  }\n  return geometry",
            "repeat",
        ),
        (
            "  s = simulate(mesh: geometry) -> {\n    return (mesh: mesh)\n  }\n  return s",
            "simulate",
        ),
        (
            "  e = foreach[FACE](geometry) -> {\n    return ()\n  }\n  return e",
            "foreach",
        ),
        (
            "  f = graph(x: Float) -> Float {\n    return x\n  }\n  return geometry",
            "closure",
        ),
    ] {
        let value = first(body);
        assert_eq!(word(&value), Some(zone));
        if let AssignValue::BodyCall(c) = &value {
            assert_eq!(refused(c), None, "{body}");
        }
    }
}

#[test]
fn a_zone_of_another_shape_is_refused() {
    let at = |line, col, m: &str| Some((line, col, m.to_owned()));
    assert_eq!(
        said("  r = repeat(s: 0.0) -> {\n    return s\n  }"),
        at(
            2,
            7,
            "repeat expects iteration count first: repeat(10, state: start, …) -> { … }"
        )
    );
    assert_eq!(
        said("  r = repeat(3) -> {\n    return 1.0\n  }"),
        at(
            2,
            7,
            "repeat expects at least one state: repeat(10, state: start) -> { … }"
        )
    );
    assert_eq!(
        said("  r = repeat(3, s(a: 1): t) -> {\n    return s\n  }"),
        at(2, 7, "repeat state does not take options")
    );
    assert_eq!(
        said("  s = simulate(geometry) -> {\n    return ()\n  }"),
        at(
            2,
            7,
            "simulate expects named states: simulate(state: start, …) -> { … }"
        )
    );
    assert_eq!(
        said("  e = foreach[FACE](item: 0.0) -> {\n    return ()\n  }"),
        at(
            2,
            7,
            "foreach expects geometry first, then named items: foreach[FACE](geometry, item: field, …) -> { … }"
        )
    );
    assert_eq!(
        said("  r = repeat[FACE](3, s: 0.0) -> {\n    return s\n  }"),
        at(2, 7, "repeat has no settings")
    );
    assert_eq!(
        said("  s = simulate[FACE](mesh: geometry) -> {\n    return (mesh: mesh)\n  }"),
        at(2, 7, "simulate has no settings")
    );
    assert_eq!(
        said("  e = foreach(geometry, a as b: 0.0) -> {\n    return ()\n  }"),
        at(2, 25, "'a as b': 'as' only aliases an item of an item node")
    );
    assert_eq!(
        said("  g = Grid(1.0, 1.0) -> {\n    return ()\n  }"),
        at(
            2,
            7,
            "'Grid' takes no body: repeat, simulate and foreach do"
        )
    );
}
