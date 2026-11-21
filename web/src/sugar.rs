//! Formulas as the nodes they write, after the add-on's `lang/sugar.py`:
//! `a * 2`, `sin(t)` are Math nodes, Vector Math when an operand is a
//! vector (`v * 2.0` scales it), `<` `==` are Compare (its data type from
//! its operands; Math in a shader tree, which has no Compare), `and` `not`
//! are Boolean Math. So `a * b` and
//! `Math(value: a, value_001: b, operation: MULTIPLY)` draw the same node:
//! its operation as its title and in its menu, its sockets as Blender
//! names them.

/// The node a formula writes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Formula {
    /// `Math`, `VectorMath`, `Compare` or `BooleanMath`.
    pub node: &'static str,
    /// Blender's identifier: `MULTIPLY`, `LESS_THAN`.
    pub operation: String,
    /// Compare's data type: `FLOAT`, `INT`, `VECTOR`, `STRING`, `RGBA`.
    pub data_type: Option<&'static str>,
    /// The operands go in the other order (a number times a vector).
    pub swap: bool,
}

pub const NODES: [&str; 4] = ["Math", "VectorMath", "Compare", "BooleanMath"];

#[derive(PartialEq, Eq, Clone, Copy)]
enum Kind {
    Scalar,
    Vector,
}

/// A type's kind; an unknown type counts as a number, as most are.
fn kind(t: Option<&str>) -> Kind {
    match t {
        Some("Vector" | "Color") => Kind::Vector,
        _ => Kind::Scalar,
    }
}

/// The node `op` (an operator, `neg`, `not`, or a function) writes on
/// operands of `types`; none when it writes none.
pub fn choose(op: &str, types: &[Option<&str>]) -> Option<Formula> {
    let formula = |node, operation: &str| Formula {
        node,
        operation: operation.to_owned(),
        data_type: None,
        swap: false,
    };
    if let Some(operation) = compare(op) {
        let data = if types.contains(&Some("String")) {
            "STRING"
        } else if !types.is_empty() && types.iter().all(|t| *t == Some("Color")) {
            "RGBA"
        } else if types.iter().any(|t| kind(*t) == Kind::Vector) {
            "VECTOR"
        } else if !types.is_empty() && types.iter().all(|t| *t == Some("Int")) {
            "INT"
        } else {
            "FLOAT"
        };
        return Some(Formula {
            data_type: Some(data),
            ..formula("Compare", operation)
        });
    }
    if let Some(operation) = match op {
        "⋅" | "·" | "dot" => Some("DOT_PRODUCT"),
        "×" | "cross" => Some("CROSS_PRODUCT"),
        _ => None,
    } {
        return Some(formula("VectorMath", operation));
    }
    if let Some(operation) = match op {
        "and" => Some("AND"),
        "or" => Some("OR"),
        "xor" => Some("XOR"),
        "not" => Some("NOT"),
        "xnor" => Some("XNOR"),
        "nand" => Some("NAND"),
        "nor" => Some("NOR"),
        "imply" => Some("IMPLY"),
        "nimply" => Some("NIMPLY"),
        _ => None,
    } {
        return Some(formula("BooleanMath", operation));
    }
    let kinds: Vec<Kind> = types.iter().map(|t| kind(*t)).collect();
    let vector = kinds.contains(&Kind::Vector);
    if op == "neg" {
        return Some(if vector {
            formula("VectorMath", "SCALE")
        } else {
            formula("Math", "MULTIPLY")
        });
    }
    if let Some(operation) = match op {
        "+" => Some("ADD"),
        "-" => Some("SUBTRACT"),
        "*" => Some("MULTIPLY"),
        "/" => Some("DIVIDE"),
        _ => None,
    } {
        if !vector {
            return Some(formula("Math", operation));
        }
        if op == "*" && kinds.len() == 2 && kinds[0] != kinds[1] {
            // A vector times a number scales it; Vector Math takes the vector first.
            return Some(Formula {
                swap: kinds[0] != Kind::Vector,
                ..formula("VectorMath", "SCALE")
            });
        }
        return Some(formula("VectorMath", operation));
    }
    if vector {
        let operation = match op {
            "sin" => "SINE",
            "cos" => "COSINE",
            "tan" => "TANGENT",
            "abs" => "ABSOLUTE",
            "min" => "MINIMUM",
            "max" => "MAXIMUM",
            "floor" => "FLOOR",
            "ceil" => "CEIL",
            "fract" => "FRACTION",
            "sign" => "SIGN",
            "mod" => "MODULO",
            "length" => "LENGTH",
            "normalize" => "NORMALIZE",
            "distance" => "DISTANCE",
            _ => return None,
        };
        return Some(formula("VectorMath", operation));
    }
    let operation = match op {
        "sin" => "SINE",
        "cos" => "COSINE",
        "tan" => "TANGENT",
        "asin" => "ARCSINE",
        "acos" => "ARCCOSINE",
        "atan" => "ARCTANGENT",
        "atan2" => "ARCTAN2",
        "sinh" => "SINH",
        "cosh" => "COSH",
        "tanh" => "TANH",
        "sqrt" => "SQRT",
        "abs" => "ABSOLUTE",
        "exp" => "EXPONENT",
        "log" => "LOGARITHM",
        "pow" => "POWER",
        "min" => "MINIMUM",
        "max" => "MAXIMUM",
        "smooth_min" => "SMOOTH_MIN",
        "smooth_max" => "SMOOTH_MAX",
        "floor" => "FLOOR",
        "ceil" => "CEIL",
        "fract" => "FRACT",
        "round" => "ROUND",
        "trunc" => "TRUNC",
        "sign" => "SIGN",
        "mod" => "MODULO",
        "radians" => "RADIANS",
        "degrees" => "DEGREES",
        // A vector function on numbers still is a Vector Math node.
        "length" => return Some(formula("VectorMath", "LENGTH")),
        "normalize" => return Some(formula("VectorMath", "NORMALIZE")),
        "distance" => return Some(formula("VectorMath", "DISTANCE")),
        _ => return None,
    };
    Some(formula("Math", operation))
}

fn compare(op: &str) -> Option<&'static str> {
    Some(match op {
        "<" => "LESS_THAN",
        "<=" => "LESS_EQUAL",
        ">" => "GREATER_THAN",
        ">=" => "GREATER_EQUAL",
        "==" => "EQUAL",
        "!=" => "NOT_EQUAL",
        _ => return None,
    })
}

/// What `==` and `!=` give Math's Compare as its Epsilon: the Epsilon of a new Compare node.
pub const EPSILON: &str = "0.001";

/// A comparison where the tree has no Compare node (a shader tree): Math's
/// operation, and whether its result is taken from 1 (`a >= b` is
/// `1 - (a < b)`).
pub fn math_compare(op: &str) -> Option<(&'static str, bool)> {
    Some(match op {
        ">" => ("GREATER_THAN", false),
        "<" => ("LESS_THAN", false),
        ">=" => ("LESS_THAN", true),
        "<=" => ("GREATER_THAN", true),
        "==" => ("COMPARE", false),
        "!=" => ("COMPARE", true),
        _ => return None,
    })
}

/// The operation a node has when its call writes none.
pub fn default_operation(node: &str) -> &'static str {
    match node {
        "Compare" => "GREATER_THAN",
        "BooleanMath" => "AND",
        _ => "ADD",
    }
}

/// How Blender shows an operation of `node`: its menu entry, and the
/// node's title.
pub fn operation_label(node: &str, operation: &str) -> String {
    let label = match (node, operation) {
        (_, "SQRT") => "Square Root",
        (_, "INVERSE_SQRT") => "Inverse Square Root",
        (_, "ABSOLUTE") => "Absolute",
        (_, "EXPONENT") => "Exponent",
        (_, "FRACT") | (_, "FRACTION") => "Fraction",
        (_, "TRUNC") => "Truncate",
        (_, "SINH") => "Hyperbolic Sine",
        (_, "COSH") => "Hyperbolic Cosine",
        (_, "TANH") => "Hyperbolic Tangent",
        (_, "ARCTAN2") => "Arctan2",
        (_, "SMOOTH_MIN") => "Smooth Minimum",
        (_, "SMOOTH_MAX") => "Smooth Maximum",
        (_, "RADIANS") => "To Radians",
        (_, "DEGREES") => "To Degrees",
        ("Math", "MODULO") => "Truncated Modulo",
        (_, "FLOORED_MODULO") => "Floored Modulo",
        (_, "PINGPONG") => "Ping-Pong",
        (_, "LESS_EQUAL") => "Less Than or Equal",
        (_, "GREATER_EQUAL") => "Greater Than or Equal",
        ("BooleanMath", "XOR") => "Not Equal",
        ("BooleanMath", "XNOR") => "Equal",
        ("BooleanMath", "NAND") => "Not And",
        ("BooleanMath", "IMPLY") => "Imply",
        ("BooleanMath", "NIMPLY") => "Subtract",
        _ => return enum_label(operation),
    };
    label.to_owned()
}

/// How Blender shows the value `value` of an enum property: `RGBA` is
/// Color, `FLOAT_VECTOR` Vector, `LESS_THAN` Less Than.
pub fn enum_label(value: &str) -> String {
    let label = match value {
        "FLOAT" => "Float",
        "INT" => "Integer",
        "INT8" => "8-Bit Integer",
        "BOOLEAN" => "Boolean",
        "VECTOR" | "FLOAT_VECTOR" | "FLOAT2" => "Vector",
        "RGBA" | "FLOAT_COLOR" | "BYTE_COLOR" => "Color",
        "QUATERNION" => "Rotation",
        "FLOAT4X4" => "Matrix",
        "STRING" => "String",
        "RGB" => "RGB",
        _ => return crate::graph::humanize(&value.to_lowercase()),
    };
    label.to_owned()
}

/// The names Blender gives the first `count` inputs of `node` doing
/// `operation`.
pub fn input_names(node: &str, operation: &str, count: usize) -> Vec<String> {
    let names: Vec<&str> = match (node, operation) {
        ("Math", "POWER") => vec!["Base", "Exponent"],
        ("Math", "LOGARITHM") => vec!["Value", "Base"],
        ("Math", "COMPARE") => vec!["Value", "Value", "Epsilon"],
        ("Math", "SMOOTH_MIN" | "SMOOTH_MAX") => vec!["Value", "Value", "Distance"],
        ("Math", "WRAP") => vec!["Value", "Max", "Min"],
        ("Math", "SNAP") => vec!["Value", "Increment"],
        ("Math", "PINGPONG") => vec!["Value", "Scale"],
        ("Math", _) => vec!["Value"; 3],
        ("VectorMath", "SCALE") => vec!["Vector", "Scale"],
        ("VectorMath", _) => vec!["Vector"; 3],
        ("Compare", _) => vec!["A", "B", "Epsilon"],
        ("BooleanMath", _) => vec!["Boolean"; 2],
        _ => vec![],
    };
    (0..count)
        .map(|i| names.get(i).copied().unwrap_or("").to_owned())
        .collect()
}

/// The output of `node` doing `operation`: its name and type.
pub fn output(node: &str, operation: &str) -> (&'static str, &'static str) {
    match (node, operation) {
        ("VectorMath", "LENGTH" | "DISTANCE" | "DOT_PRODUCT") => ("Value", "Float"),
        ("VectorMath", _) => ("Vector", "Vector"),
        ("Compare", _) => ("Result", "Bool"),
        ("BooleanMath", _) => ("Boolean", "Bool"),
        _ => ("Value", "Float"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn as_the_add_on_chooses() {
        let f = choose("*", &[Some("Float"), Some("Float")]).unwrap();
        assert_eq!((f.node, f.operation.as_str()), ("Math", "MULTIPLY"));
        let f = choose("*", &[Some("Float"), Some("Vector")]).unwrap();
        assert_eq!(
            (f.node, f.operation.as_str(), f.swap),
            ("VectorMath", "SCALE", true)
        );
        let f = choose("==", &[Some("Int"), Some("Int")]).unwrap();
        assert_eq!((f.node, f.data_type), ("Compare", Some("INT")));
        let f = choose("sin", &[Some("Vector")]).unwrap();
        assert_eq!(f.node, "VectorMath");
        assert_eq!(choose("not", &[None]).unwrap().node, "BooleanMath");
        assert!(choose("noise", &[None]).is_none());
    }

    #[test]
    fn labels_as_blender_shows_them() {
        assert_eq!(operation_label("Math", "MULTIPLY"), "Multiply");
        assert_eq!(
            operation_label("Compare", "LESS_EQUAL"),
            "Less Than or Equal"
        );
        assert_eq!(operation_label("BooleanMath", "XOR"), "Not Equal");
        assert_eq!(enum_label("RGBA"), "Color");
        assert_eq!(input_names("Math", "POWER", 2), ["Base", "Exponent"]);
    }
}
