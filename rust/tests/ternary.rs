//! `cond ? a : b`: it binds loosest and chains to the right, prints back with the parentheses it
//! needs, and breaks before each branch when too long. The Python parser and printer have the same
//! cases (python/tests/test_ternary.py).

use base_node::ast::{AssignValue, Expr, Stmt};
use base_node::{format_source, parse};

const SIG: &str =
    "geometry graph g(geometry: Geometry, a: Float, b: Float, i: Int, v: Vector, on: Bool) -> Geometry";

fn graph(body: &str) -> String {
    format!("{SIG} {{\n{body}\n  return geometry\n}}\n")
}

fn value(text: &str) -> Expr {
    let file = parse(&graph(&format!("  x = {text}")), "t.bn").unwrap();
    match &file.graphs[0].body[0] {
        Stmt::Assign(a) => match &a.value {
            AssignValue::Expr(e) => e.clone(),
            _ => panic!("not an expression"),
        },
        _ => panic!("not an assignment"),
    }
}

#[test]
fn binds_loosest_and_chains_to_the_right() {
    let Expr::Cond(c) = value("a > b or on ? a + 1.0 : b * 2.0") else {
        panic!("not a ternary")
    };
    assert!(matches!(&*c.cond, Expr::BinOp(b) if b.op == "or"));
    assert!(matches!(&*c.then, Expr::BinOp(b) if b.op == "+"));
    assert!(matches!(&*c.orelse, Expr::BinOp(b) if b.op == "*"));
    let Expr::Cond(c) = value("on ? a : a > b ? b : 0.0") else {
        panic!("not a ternary")
    };
    assert!(matches!(&*c.orelse, Expr::Cond(_)));
    let Expr::Cond(c) = value("on ? a > b ? 1.0 : 2.0 : 3.0") else {
        panic!("not a ternary")
    };
    assert!(matches!(&*c.then, Expr::Cond(_)));
    let Expr::Cond(c) = value("on ? geometry |> SubdivideMesh() : geometry") else {
        panic!("not a ternary")
    };
    assert!(matches!(&*c.then, Expr::Pipe(_)));
    let Expr::Pipe(p) = value("(on ? geometry : geometry) |> SubdivideMesh()") else {
        panic!("not a pipe")
    };
    assert!(matches!(&*p.left, Expr::Cond(_)));
}

#[test]
fn wants_both_branches() {
    for (text, message) in [
        (
            "on ? a",
            "expected ':' and the value when the condition is false, cond ? a : b, found",
        ),
        ("on ? : b", "found ':'"),
    ] {
        let err = parse(&graph(&format!("  x = {text}")), "t.bn").unwrap_err();
        assert!(err.to_string().contains(message), "{text}: {err}");
    }
}

#[test]
fn prints_back_with_the_parentheses_it_needs() {
    for body in [
        "  x = on ? a : b",
        "  x = on ? a : a > b ? b : 0.0",
        "  x = on ? (a > b ? 1.0 : 2.0) : 3.0",
        "  x = (on ? a > 0.0 : a > b) ? 1.0 : 2.0",
        "  x = (on ? a : b) * 2.0 + (a > b ? 1.0 : 0.0)",
        "  x = -(on ? a : b)",
        "  x = not (on ? on : a > b)",
        "  x = on ? SubdivideMesh(geometry) |> SetShadeSmooth() : geometry",
        "  x = (on ? geometry : SubdivideMesh(geometry))\n    |> SetShadeSmooth()",
        "  x = Switch(switch: on ? a : b, true_: on ? (1.0, 0.0, 0.0) : v)",
        "  x = SeparateXYZ(vector: on ? v : (0.0, 0.0, 1.0)).z",
    ] {
        assert_eq!(format_source(&graph(body), "t.bn").unwrap(), graph(body));
    }
    assert_eq!(
        format_source(&graph("  x = (on) ? (a) : (a > b ? b : 0.0)"), "t.bn").unwrap(),
        graph("  x = on ? a : a > b ? b : 0.0")
    );
    assert_eq!(
        format_source(&graph("  x = on?a:b  // this one"), "t.bn").unwrap(),
        graph("  x = on ? a : b  // this one")
    );
}

#[test]
fn a_long_one_breaks_before_each_branch() {
    let long = "  x = a_condition_with_a_long_name_of_its_own > another_long_name_for_the_other_side ? \
                the_first_branch_and_its_long_name * 2.0 : the_second_branch_and_its_long_name + 1.0";
    assert_eq!(
        format_source(&graph(long), "t.bn").unwrap(),
        graph(
            "  x = a_condition_with_a_long_name_of_its_own > another_long_name_for_the_other_side\n    \
             ? the_first_branch_and_its_long_name * 2.0\n    \
             : the_second_branch_and_its_long_name + 1.0"
        )
    );
    let nested = format_source(
        &graph(
            "  x = on ? a : a_condition_with_a_long_name_of_its_own > another_long_name_for_the_other_side ? \
             the_first_branch_and_its_long_name * 2.0 + another_term_to_make_it_long : the_second_branch + 1.0",
        ),
        "t.bn",
    )
    .unwrap();
    assert_eq!(
        nested,
        graph(
            "  x = on\n    ? a\n    \
             : a_condition_with_a_long_name_of_its_own > another_long_name_for_the_other_side\n      \
             ? the_first_branch_and_its_long_name * 2.0 + another_term_to_make_it_long\n      \
             : the_second_branch + 1.0"
        )
    );
    assert_eq!(format_source(&nested, "t.bn").unwrap(), nested);
}
