use base_node::{format_source, parse};

const SIMULATE: &str = r#"geometry graph g(geometry: Geometry) -> Geometry {
  s = simulate(mesh: geometry, "Delta Time" as delta_time_2: 0.0) -> {
    return (mesh: mesh, delta_time_2: delta_time_2 + delta_time)
  }
  return s.mesh
}
"#;

#[test]
fn a_state_takes_a_key_of_its_own() {
    // A state named like the zone's own name, as Blender lets one call it, goes by a key
    parse(SIMULATE, "t.bn").expect("simulate state with a key");
    assert_eq!(format_source(SIMULATE, "t.bn").expect("formats"), SIMULATE);
    let repeat = "geometry graph g(geometry: Geometry) -> Geometry {\n  r = repeat(2, Iteration as it: 0.0) -> {\n    return it\n  }\n  return geometry\n}\n";
    parse(repeat, "t.bn").expect("repeat state with a key");
}

#[test]
fn any_call_with_a_body_reads() {
    // Which names take a body, and with which arguments, a host says: the core reads them all
    let src = "kind graph g(a: Float) -> Float {\n  e = m::each(a, b as c: 0.0) -> {\n    return ()\n  }\n  f = graph(x: Float) -> Float {\n    return x\n  }\n  return e\n}\n";
    let file = parse(src, "t.bn").expect("a call with a body, a graph with no name");
    assert_eq!(format_source(src, "t.bn").unwrap(), src);
    let values: Vec<_> = file.graphs[0]
        .body
        .iter()
        .filter_map(|s| match s {
            base_node::ast::Stmt::Assign(a) => Some(&a.value),
            _ => None,
        })
        .collect();
    assert!(
        matches!(values[0], base_node::ast::AssignValue::BodyCall(c) if c.name == "m::each" && c.args.len() == 2)
    );
    assert!(matches!(
        values[1],
        base_node::ast::AssignValue::NamelessGraph(_)
    ));
}

#[test]
fn a_body_is_the_value_of_an_assignment() {
    let nested = "kind graph g(a: Float) -> Float {\n  return each(a) -> {\n    return a\n  }\n}\n";
    let e = parse(nested, "t.bn").unwrap_err();
    assert_eq!(
        e.diagnostics[0].to_string(),
        "t.bn:2:10: a call with a body is the value of an assignment: r = each(…) -> { … }"
    );
    let graph = "kind graph g(a: Float) -> Float {\n  return graph(x: Float) -> Float {\n    return x\n  }\n}\n";
    let e = parse(graph, "t.bn").unwrap_err();
    assert_eq!(
        e.diagnostics[0].message,
        "a graph with no name is the value of an assignment: f = graph(x: Float) -> Float { … }"
    );
}

#[test]
fn a_call_then_a_frame_with_no_title_is_no_body() {
    // The arrow makes the body: without it, the brace opens a frame, whatever the call's name
    let src =
        "kind graph g(a: Float) -> Float {\n  x = repeat(a)\n  {\n    y = x\n  }\n  return y\n}\n";
    let file = parse(src, "t.bn").unwrap();
    assert_eq!(file.graphs[0].body.len(), 3);
    assert_eq!(format_source(src, "t.bn").unwrap(), src);
}
