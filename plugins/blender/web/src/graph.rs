//! From base-node's syntax tree to a graph of nodes, without knowing any
//! host's node types: a node per call (or operator), a link per argument,
//! a Group Input for the parameters, a Group Output for what is returned,
//! a frame per frame, an input and output node per zone. A socket's name
//! is the argument's (a positional one has none, unless the callee is a
//! graph of the same text), its type what flows into it when known.
//! Variables are evaluated when first needed, as their order does not
//! matter; the nodes of a statement go into its frame. For any tree kind,
//! read-only.

use std::collections::HashMap;

use crate::sugar;
use base_node::ast::{
    flatten, Arg, AssignValue, Call, Expr, File, Graph, Param, ReturnValue, Setting, Stmt,
};
use base_node_blender::targets::setting_of;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Category {
    Input,
    Output,
    Converter,
    Vector,
    Texture,
    Geometry,
    Shader,
    Group,
    Zone,
}

impl Category {
    pub fn class(self) -> &'static str {
        match self {
            Category::Input => "input",
            Category::Output => "output",
            Category::Converter => "converter",
            Category::Vector => "vector",
            Category::Texture => "texture",
            Category::Geometry => "geometry",
            Category::Shader => "shader",
            Category::Group => "group",
            Category::Zone => "zone",
        }
    }
}

#[derive(Clone, Debug)]
pub struct Input {
    pub name: String,
    pub ty: Option<String>,
    /// The value of an unlinked input, as written.
    pub value: Option<String>,
    /// The node and output it is linked from.
    pub link: Option<(usize, usize)>,
}

#[derive(Clone, Debug)]
pub struct Output {
    pub name: String,
    pub ty: Option<String>,
}

#[derive(Clone, Debug)]
pub struct Node {
    pub title: String,
    pub category: Category,
    /// A header color from the text (`#red`), else the category's.
    pub color: Option<String>,
    pub inputs: Vec<Input>,
    pub outputs: Vec<Output>,
    /// Its settings, as their menus show them (`Multiply`, `Color`):
    /// between its outputs and its inputs, like Blender's.
    pub settings: Vec<String>,
    pub frame: Option<usize>,
    /// The line of the text it comes from (1-based).
    pub line: usize,
    /// The comments of the text shown over it, and under it (a zone's end).
    pub above: Vec<String>,
    pub below: Vec<String>,
    /// Its default output's name, the variable it is assigned to.
    hint: Option<String>,
}

#[derive(Clone, Debug)]
pub struct Frame {
    pub label: String,
    pub color: Option<String>,
    /// A zone's frame (Repeat, Simulation…), not a frame of the text.
    pub zone: bool,
    /// The frame it is in.
    pub parent: Option<usize>,
    /// The comments of the head of its block, and of its end.
    pub above: Vec<String>,
    pub below: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct Tree {
    pub name: String,
    pub kind: String,
    pub description: Option<String>,
    pub nodes: Vec<Node>,
    pub frames: Vec<Frame>,
    /// The comments of the graph itself (and of the file's head, on its
    /// last graph), in a corner of the editor.
    pub notes: Vec<String>,
    /// The places of the text its comments go with, in its order.
    pub places: Vec<Place>,
}

/// A place of the text comments go with: a statement or the head of a
/// block (`close` false), or the end of a block.
#[derive(Clone, Copy, Debug)]
pub struct Place {
    pub line: usize,
    pub close: bool,
    /// None for a statement that makes no node of its own.
    pub holder: Option<Holder>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Holder {
    Tree,
    Node(usize),
    Frame(usize),
}

/// A place while the tree is built: an assignment's node is known once it
/// is evaluated.
#[derive(Clone, Copy, Debug)]
enum Pending {
    Done(Holder),
    Assign(usize),
}

/// What an expression gives: a node's output, a node whose output is not
/// chosen yet (its default one), or a value written in the text.
#[derive(Clone, Debug)]
enum Val {
    Out(usize, usize),
    Node(usize),
    Lit(String, Option<&'static str>),
}

enum Bind<'a> {
    Lazy(
        &'a AssignValue,
        Option<usize>,
        Option<&'a base_node::ast::Look>,
        usize,
    ),
    Busy,
    Done(Val),
}

struct Builder<'a> {
    nodes: Vec<Node>,
    frames: Vec<Frame>,
    scopes: Vec<HashMap<String, Bind<'a>>>,
    params: HashMap<String, (usize, usize)>,
    graphs: HashMap<String, &'a Graph>,
    frame: Option<usize>,
    /// The Separate XYZ of a node's output, made once.
    separate: HashMap<(usize, usize), usize>,
    places: Vec<(usize, bool, Pending)>,
    /// The node of the assignment of each line.
    assigned: HashMap<usize, usize>,
    /// A shader tree has no Compare node: a comparison is Math there.
    shader: bool,
    /// A geometry tree's Switch chooses for each element: a ternary is one there, a Mix elsewhere.
    geometry: bool,
    /// The kind of the tree: where a setting written by position goes depends on its nodes.
    kind: &'a str,
}

pub fn trees(file: &File) -> Vec<Tree> {
    let mut graphs = HashMap::new();
    for g in &file.graphs {
        graphs.insert(g.name.clone(), g);
        graphs.insert(base_node::ast::key(&g.name), g);
    }
    file.graphs.iter().map(|g| tree(g, &graphs)).collect()
}

fn tree<'a>(graph: &'a Graph, graphs: &HashMap<String, &'a Graph>) -> Tree {
    let mut b = Builder {
        nodes: Vec::new(),
        frames: Vec::new(),
        scopes: vec![HashMap::new()],
        params: HashMap::new(),
        graphs: graphs.clone(),
        frame: None,
        separate: HashMap::new(),
        places: vec![(graph.line, false, Pending::Done(Holder::Tree))],
        assigned: HashMap::new(),
        shader: graph.kind == "shader",
        geometry: graph.kind == "geometry",
        kind: &graph.kind,
    };
    let params = flatten(&graph.tree("INPUT"));
    if !params.is_empty() {
        let n = b.push(Node::new("Group Input", Category::Input, graph.line));
        for p in &params {
            b.params
                .insert(p.name.clone(), (n, b.nodes[n].outputs.len()));
            b.nodes[n].outputs.push(Output {
                name: p.name.clone(),
                ty: Some(p.type_name.clone()),
            });
        }
    }
    let mut returns = Vec::new();
    b.collect(&graph.body, None, &mut returns);
    let outputs = flatten(&graph.tree("OUTPUT"));
    let mut out = Node::new("Group Output", Category::Output, graph.end.max(graph.line));
    out.inputs = outputs
        .iter()
        .map(|o| Input {
            name: o.name.clone(),
            ty: Some(o.type_name.clone()),
            value: None,
            link: None,
        })
        .collect();
    let mut links = Vec::new();
    let return_lines: Vec<usize> = returns.iter().map(|(r, _)| r.line).collect();
    for (ret, frame) in returns {
        b.frame = frame;
        if let Some(l) = ret.look.as_ref() {
            if let Some(label) = &l.label {
                out.title = label.clone();
            }
        }
        out.line = ret.line;
        links.extend(b.returned(&ret.value, &outputs));
    }
    b.frame = None;
    b.finish_scope();
    let out_n = b.push(out);
    for (i, val) in links {
        b.connect(out_n, i, val);
    }
    for line in return_lines {
        b.places
            .push((line, false, Pending::Done(Holder::Node(out_n))));
    }
    b.places
        .push((graph.end, true, Pending::Done(Holder::Tree)));
    let mut places: Vec<Place> = b
        .places
        .iter()
        .map(|&(line, close, p)| Place {
            line,
            close,
            holder: match p {
                Pending::Done(h) => Some(h),
                Pending::Assign(l) => b.assigned.get(&l).map(|&n| Holder::Node(n)),
            },
        })
        .collect();
    places.sort_by_key(|p| p.line);
    Tree {
        name: graph.name.clone(),
        kind: graph.kind.clone(),
        description: graph.description.clone(),
        nodes: b.nodes,
        frames: b.frames,
        notes: Vec::new(),
        places,
    }
}

impl Node {
    fn new(title: impl Into<String>, category: Category, line: usize) -> Self {
        Node {
            title: title.into(),
            category,
            color: None,
            inputs: Vec::new(),
            outputs: Vec::new(),
            settings: Vec::new(),
            frame: None,
            line,
            above: Vec::new(),
            below: Vec::new(),
            hint: None,
        }
    }
}

impl<'a> Builder<'a> {
    fn push(&mut self, mut node: Node) -> usize {
        if node.frame.is_none() {
            node.frame = self.frame;
        }
        self.nodes.push(node);
        self.nodes.len() - 1
    }

    /// The assignments of `body` into the current scope (each with its
    /// frame), and its returns into `returns`.
    fn collect(
        &mut self,
        body: &'a [Stmt],
        frame: Option<usize>,
        returns: &mut Vec<(&'a base_node::ast::Return, Option<usize>)>,
    ) {
        for stmt in body {
            match stmt {
                Stmt::Assign(a) => {
                    let scope = self.scopes.last_mut().expect("a scope");
                    scope.insert(
                        a.name.clone(),
                        Bind::Lazy(&a.value, frame, a.look.as_ref(), a.line),
                    );
                    self.places.push((a.line, false, Pending::Assign(a.line)));
                }
                Stmt::Return(r) => returns.push((r, frame)),
                Stmt::Frame(f) => {
                    self.frames.push(Frame {
                        label: f.label.clone().unwrap_or_default(),
                        color: f.color.as_deref().and_then(css_color),
                        zone: false,
                        parent: frame,
                        above: Vec::new(),
                        below: Vec::new(),
                    });
                    let index = self.frames.len() - 1;
                    let at = Pending::Done(Holder::Frame(index));
                    self.places.push((f.line, false, at));
                    self.places.push((f.end, true, at));
                    self.collect(&f.body, Some(index), returns);
                }
            }
        }
    }

    /// The variables of the current scope nothing used yet: their nodes
    /// are in the tree all the same.
    fn finish_scope(&mut self) {
        let mut names: Vec<String> = self
            .scopes
            .last()
            .map(|s| s.keys().cloned().collect())
            .unwrap_or_default();
        names.sort_by_key(|n| (self.line_of(n), n.clone()));
        for name in names {
            self.var(&name);
        }
    }

    fn line_of(&self, name: &str) -> usize {
        match self.scopes.last().and_then(|s| s.get(name)) {
            Some(Bind::Lazy(v, _, _, _)) => match v {
                AssignValue::Expr(e) => e.line(),
                AssignValue::BodyCall(z) => z.line,
                AssignValue::NamelessGraph(z) => z.line,
            },
            _ => 0,
        }
    }

    /// The value of the variable `name`, evaluated on first use; none
    /// when no scope has it.
    fn var(&mut self, name: &str) -> Option<Val> {
        let depth = (0..self.scopes.len())
            .rev()
            .find(|&d| self.scopes[d].contains_key(name))?;
        let key = name.to_owned();
        match self.scopes[depth].insert(key.clone(), Bind::Busy) {
            Some(Bind::Done(v)) => {
                self.scopes[depth].insert(key, Bind::Done(v.clone()));
                Some(v)
            }
            Some(Bind::Busy) | None => Some(Val::Lit(name.to_owned(), None)),
            Some(Bind::Lazy(value, frame, look, line)) => {
                let saved = self.frame;
                self.frame = frame;
                let first = self.nodes.len();
                let v = self.assigned(value);
                if let Some(n) = value_node(&v) {
                    if n >= first {
                        self.assigned.entry(line).or_insert(n);
                    }
                    if n >= first && self.nodes[n].hint.is_none() {
                        self.nodes[n].hint = Some(key.clone());
                    }
                    if let Some(look) = look {
                        if let Some(label) = &look.label {
                            self.nodes[n].title = label.clone();
                        }
                        if let Some(c) = look.color.as_deref().and_then(css_color) {
                            self.nodes[n].color = Some(c);
                        }
                    }
                }
                self.frame = saved;
                self.scopes[depth].insert(key, Bind::Done(v.clone()));
                Some(v)
            }
        }
    }

    fn assigned(&mut self, value: &'a AssignValue) -> Val {
        match value {
            AssignValue::Expr(e) => self.expr(e),
            // A call with a body is one of Blender's zones by its name; its first argument, when
            // it has no name, is what the zone runs on: the count of a repeat, what a foreach walks
            AssignValue::BodyCall(z) => {
                let (head, title, own) = match z.name.as_str() {
                    "repeat" => ("Iterations", "Repeat", "iteration"),
                    "simulate" => ("", "Simulation", "delta_time"),
                    "foreach" => ("Geometry", "For Each Element", "Element"),
                    name => ("", name, ""),
                };
                let first = z
                    .args
                    .first()
                    .filter(|a| a.name.is_none() && !head.is_empty());
                let items = &z.args[usize::from(first.is_some())..];
                let mut ins = Vec::new();
                if let Some(a) = first {
                    ins.push((head.to_owned(), self.expr(&a.value)));
                }
                ins.extend(self.state_args(items));
                let states = arg_names(items);
                let mut inner = Vec::new();
                if !own.is_empty() {
                    inner.push(own.to_owned());
                }
                inner.extend(states.iter().cloned());
                let outs = if z.name == "foreach" {
                    vec!["Geometry".to_owned()]
                } else {
                    states
                };
                // `foreach[FACE](…)`: the domain on the zone's input, as its menu shows it
                let settings = z.settings.iter().filter_map(setting_label).collect();
                self.zone(
                    title,
                    (z.line, z.end),
                    ins,
                    settings,
                    &inner,
                    &outs,
                    &z.body,
                )
            }
            AssignValue::NamelessGraph(z) => {
                let params: Vec<String> = z.params.iter().map(|p| p.name.clone()).collect();
                let outs: Vec<String> = z.outputs.iter().map(|p| p.name.clone()).collect();
                self.zone(
                    "Closure",
                    (z.line, z.end),
                    Vec::new(),
                    Vec::new(),
                    &params,
                    &outs,
                    &z.body,
                )
            }
        }
    }

    fn state_args(&mut self, args: &'a [Arg]) -> Vec<(String, Val)> {
        args.iter()
            .map(|a| (a.name.clone().unwrap_or_default(), self.expr(&a.value)))
            .collect()
    }

    /// A zone: its input node (taking `ins`, giving `inner` to its body,
    /// showing `settings`), its body in a scope of its own, its output node
    /// (taking what the body returns, giving `outs`), all in a frame of the
    /// zone's.
    #[allow(clippy::too_many_arguments)]
    fn zone(
        &mut self,
        title: &str,
        (line, end): (usize, usize),
        ins: Vec<(String, Val)>,
        settings: Vec<String>,
        inner: &[String],
        outs: &[String],
        body: &'a [Stmt],
    ) -> Val {
        let saved = self.frame;
        self.frames.push(Frame {
            label: title.to_owned(),
            color: None,
            zone: true,
            parent: saved,
            above: Vec::new(),
            below: Vec::new(),
        });
        self.frame = Some(self.frames.len() - 1);
        let mut input = Node::new(format!("{title} Input"), Category::Zone, line);
        input.settings = settings;
        input.outputs = inner
            .iter()
            .map(|n| Output {
                name: humanize(n),
                ty: None,
            })
            .collect();
        let input_n = self.push(input);
        for (name, val) in ins {
            self.add_input(input_n, humanize(&name), val);
        }
        self.scopes.push(HashMap::new());
        for (i, n) in inner.iter().enumerate() {
            self.scopes
                .last_mut()
                .expect("a scope")
                .insert(n.clone(), Bind::Done(Val::Out(input_n, i)));
        }
        let mut returns = Vec::new();
        let frame = self.frame;
        self.collect(body, frame, &mut returns);
        let params: Vec<Param> = outs
            .iter()
            .map(|o| Param {
                name: o.clone(),
                type_name: String::new(),
                line,
                col: 0,
                default: None,
                range: None,
                options: Vec::new(),
                alias: None,
            })
            .collect();
        let mut links = Vec::new();
        let mut lines = Vec::new();
        for (ret, _) in returns {
            lines.push(ret.line);
            links.extend(self.returned(&ret.value, &params));
        }
        self.finish_scope();
        self.scopes.pop();
        let mut output = Node::new(format!("{title} Output"), Category::Zone, line);
        output.inputs = outs
            .iter()
            .map(|o| Input {
                name: humanize(o),
                ty: None,
                value: None,
                link: None,
            })
            .collect();
        output.outputs = outs
            .iter()
            .map(|o| Output {
                name: humanize(o),
                ty: None,
            })
            .collect();
        if title == "Closure" {
            output.outputs = vec![Output {
                name: "Closure".into(),
                ty: Some("Closure".into()),
            }];
        }
        let out_n = self.push(output);
        // The zone's comments go on its output: its return's over it, its end's under it.
        for l in lines {
            self.places
                .push((l, false, Pending::Done(Holder::Node(out_n))));
        }
        self.places
            .push((end, true, Pending::Done(Holder::Node(out_n))));
        for (i, val) in links {
            self.connect(out_n, i, val);
        }
        for i in 0..self.nodes[out_n].outputs.len() {
            let ty = self.nodes[out_n].inputs.get(i).and_then(|s| s.ty.clone());
            if ty.is_some() && title != "Closure" {
                self.nodes[out_n].outputs[i].ty = ty;
            }
        }
        self.frame = saved;
        Val::Node(out_n)
    }

    /// What a return gives to the inputs of an output node with `outputs`:
    /// (input index, value).
    fn returned(&mut self, value: &'a ReturnValue, outputs: &[Param]) -> Vec<(usize, Val)> {
        match value {
            ReturnValue::Expr(e) => vec![(0, self.expr(e))],
            ReturnValue::Record(r) => r
                .fields
                .iter()
                .enumerate()
                .map(|(i, f)| {
                    let at = f
                        .name
                        .as_ref()
                        .and_then(|n| outputs.iter().position(|o| &o.name == n || o.key() == *n))
                        .unwrap_or(i);
                    (at, self.expr(&f.value))
                })
                .collect(),
        }
    }

    fn expr(&mut self, e: &'a Expr) -> Val {
        match e {
            Expr::Number(n) => Val::Lit(
                number(n.value, n.is_int),
                Some(if n.is_int { "Int" } else { "Float" }),
            ),
            Expr::String(s) => Val::Lit(base_node::ast::quote(&s.value), Some("String")),
            Expr::Bool(b) => Val::Lit(b.value.to_string(), Some("Bool")),
            Expr::Tuple(t) => {
                let items: Vec<Val> = t.items.iter().map(|i| self.expr(i)).collect();
                let written: Option<Vec<String>> = items
                    .iter()
                    .map(|v| match v {
                        Val::Lit(s, _) => Some(s.clone()),
                        _ => None,
                    })
                    .collect();
                if let Some(text) = written {
                    let ty = if items.len() == 4 { "Color" } else { "Vector" };
                    Val::Lit(format!("({})", text.join(", ")), Some(ty))
                } else {
                    let names = ["X", "Y", "Z", "W"];
                    let n = self.push(Node::new("Combine XYZ", Category::Converter, t.line));
                    for (i, v) in items.into_iter().enumerate() {
                        self.add_input(n, names.get(i).unwrap_or(&"").to_string(), v);
                    }
                    self.nodes[n].outputs.push(Output {
                        name: "Vector".into(),
                        ty: Some("Vector".into()),
                    });
                    Val::Out(n, 0)
                }
            }
            Expr::Ref(r) => {
                if let Some(v) = self.var(&r.name) {
                    v
                } else if let Some(&(n, o)) = self.params.get(&r.name) {
                    Val::Out(n, o)
                } else {
                    Val::Lit(r.name.clone(), None)
                }
            }
            Expr::Member(m) => {
                let target = self.expr(&m.target);
                self.member(target, &m.socket, m.line)
            }
            Expr::Call(c) => self.call(c, None),
            Expr::Pipe(p) => {
                let left = self.expr(&p.left);
                match p.call.as_ref() {
                    Expr::Call(c) => self.call(c, Some(left)),
                    other => self.expr(other),
                }
            }
            Expr::BinOp(b) => {
                let l = self.expr(&b.left);
                let r = self.expr(&b.right);
                self.formula(&b.op, b.line, vec![l, r])
            }
            Expr::Neg(n) => {
                let v = self.expr(&n.value);
                if let Val::Lit(s, ty) = &v {
                    return Val::Lit(format!("-{s}"), *ty);
                }
                self.formula(
                    "neg",
                    n.line,
                    vec![v, Val::Lit("-1.0".into(), Some("Float"))],
                )
            }
            Expr::Not(n) => {
                let v = self.expr(&n.value);
                self.formula("not", n.line, vec![v])
            }
            Expr::Cond(c) => self.ternary(c),
        }
    }

    /// The node `cond ? then : orelse` writes, drawn as its call is: a Switch in a geometry tree;
    /// elsewhere a Mix by the condition, a Mix Shader when a branch is a shader.
    fn ternary(&mut self, c: &'a base_node::ast::Cond) -> Val {
        // Before its values, as a call
        let n = self.push(Node::new(String::new(), Category::Converter, c.line));
        let cond = self.expr(&c.cond);
        let then = self.expr(&c.then);
        let orelse = self.expr(&c.orelse);
        // A node of shaders gives one, when its outputs are not known
        let shader = [&orelse, &then].iter().any(|v| {
            self.type_of(v).as_deref() == Some("Shader")
                || matches!(v, Val::Node(m) if self.nodes[*m].category == Category::Shader)
        });
        let (name, keys) = if self.geometry {
            ("Switch", ["switch", "false_", "true_"])
        } else if shader {
            ("MixShader", ["factor", "Shader", "Shader"])
        } else {
            ("Mix", ["factor", "a", "b"])
        };
        self.nodes[n].title = humanize(name);
        self.nodes[n].category = category(name);
        for (key, v) in keys.iter().zip([cond, orelse, then]) {
            self.add_input(n, socket_label(key), v);
        }
        Val::Node(n)
    }

    /// The type of what `v` gives, when known.
    fn type_of(&mut self, v: &Val) -> Option<String> {
        match v {
            Val::Lit(_, ty) => ty.map(str::to_owned),
            Val::Out(n, o) => self.nodes[*n].outputs[*o].ty.clone(),
            Val::Node(n) => {
                let o = self.default_output(*n);
                self.nodes[*n].outputs[o].ty.clone()
            }
        }
    }

    /// The node the formula `op` over `args` writes, as the add-on writes it.
    fn formula(&mut self, op: &str, line: usize, mut args: Vec<Val>) -> Val {
        let types: Vec<Option<String>> = args.iter().map(|a| self.type_of(a)).collect();
        let types: Vec<Option<&str>> = types.iter().map(Option::as_deref).collect();
        if let Some((operation, negated)) = sugar::math_compare(op).filter(|_| self.shader) {
            // A Float 0 or 1; `>=`, `<=` and `!=` are the opposite one taken from 1.
            let mut args: Vec<(Option<String>, Val)> =
                args.into_iter().map(|v| (None, v)).collect();
            if operation == "COMPARE" {
                args.push((None, Val::Lit(sugar::EPSILON.to_owned(), Some("Float"))));
            }
            let v = self.math_node("Math", operation, None, line, args);
            if !negated {
                return v;
            }
            let one = Val::Lit("1.0".to_owned(), Some("Float"));
            return self.math_node("Math", "SUBTRACT", None, line, vec![(None, one), (None, v)]);
        }
        let Some(f) = sugar::choose(op, &types) else {
            let n = self.push(Node::new(op, Category::Converter, line));
            for v in args {
                self.add_input(n, String::new(), v);
            }
            return Val::Node(n);
        };
        if f.swap {
            args.swap(0, 1);
        }
        // Compare's data type only when its operands' types are known.
        let data_type = if types.iter().any(Option::is_none) {
            None
        } else {
            f.data_type.map(str::to_owned)
        };
        let args = args.into_iter().map(|v| (None, v)).collect();
        self.math_node(f.node, &f.operation, data_type, line, args)
    }

    /// A Math, Vector Math, Compare or Boolean Math node doing `operation`
    /// over `args` (each named by its socket key, or by its place): titled
    /// by its operation, its settings in menus, its sockets named as
    /// Blender names them.
    fn math_node(
        &mut self,
        node: &str,
        operation: &str,
        data_type: Option<String>,
        line: usize,
        args: Vec<(Option<String>, Val)>,
    ) -> Val {
        let category = if node == "VectorMath" {
            Category::Vector
        } else {
            Category::Converter
        };
        let mut n = Node::new(sugar::operation_label(node, operation), category, line);
        if let Some(d) = &data_type {
            n.settings.push(sugar::enum_label(d));
        }
        n.settings.push(sugar::operation_label(node, operation));
        let (out, ty) = sugar::output(node, operation);
        n.outputs.push(Output {
            name: out.to_owned(),
            ty: Some(ty.to_owned()),
        });
        let names = sugar::input_names(node, operation, args.len());
        let n = self.push(n);
        for (i, (name, v)) in args.into_iter().enumerate() {
            let name = match name {
                Some(key) => socket_label(&key),
                None => names[i].clone(),
            };
            self.add_input(n, name, v);
        }
        Val::Out(n, 0)
    }

    /// The setting of `node` a setting in brackets is: its name, or where
    /// a positional one goes in a tree of this kind (in any of Blender's
    /// trees for a kind that is not one of them).
    fn setting_name(&self, node: &str, s: &Setting) -> Option<String> {
        if let Some(n) = &s.name {
            return Some(n.clone());
        }
        let Expr::Ref(r) = &s.value else { return None };
        std::iter::once(self.kind)
            .chain(["geometry", "shader", "compositor"])
            .find_map(|k| setting_of(k, node, &r.name))
            .map(str::to_owned)
    }

    fn call(&mut self, c: &'a Call, piped: Option<Val>) -> Val {
        // `sin(t)`, `length(v)`: a function of the language, unless a graph
        // of the text has its name.
        if !self.graphs.contains_key(&c.name) && sugar::choose(&c.name, &[None]).is_some() {
            let mut args: Vec<Val> = piped.into_iter().collect();
            args.extend(c.args.iter().map(|a| self.expr(&a.value)));
            return self.formula(&c.name, c.line, args);
        }
        // `Math[MULTIPLY](value: a, value_001: b)`: the same node.
        if sugar::NODES.contains(&c.name.as_str()) {
            let mut operation = None;
            let mut data_type = None;
            let mut others = Vec::new();
            for s in &c.settings {
                let word = match &s.value {
                    Expr::Ref(r) => Some(r.name.clone()),
                    _ => None,
                };
                match (self.setting_name(&c.name, s).as_deref(), word) {
                    (Some("operation"), Some(v)) => operation = Some(v),
                    (Some("data_type"), Some(v)) => data_type = Some(v),
                    _ => others.extend(setting_label(s)),
                }
            }
            let mut args: Vec<(Option<String>, Val)> =
                piped.into_iter().map(|v| (None, v)).collect();
            for a in &c.args {
                let v = self.expr(&a.value);
                args.push((a.name.clone(), v));
            }
            if c.name == "Compare" && data_type.is_none() {
                data_type = Some("FLOAT".to_owned());
            }
            let operation =
                operation.unwrap_or_else(|| sugar::default_operation(&c.name).to_owned());
            let v = self.math_node(&c.name, &operation, data_type, c.line, args);
            if let Val::Out(n, _) = v {
                self.nodes[n].settings.extend(others);
            }
            return v;
        }
        let local = self.graphs.get(&c.name).copied();
        let category = match local {
            Some(_) => Category::Group,
            None => category(&c.name),
        };
        let title = match local {
            Some(g) => g.name.clone(),
            None if category == Category::Group => c.name.clone(),
            None => humanize(&c.name),
        };
        let params: Vec<Param> = local.map(|g| flatten(&g.tree("INPUT"))).unwrap_or_default();
        let mut node = Node::new(title, category, c.line);
        if let Some(outs) = &c.outputs {
            node.outputs = outs
                .iter()
                .map(|o| Output {
                    name: o.name.clone(),
                    ty: Some(o.type_name.clone()),
                })
                .collect();
        } else if let Some(g) = local {
            node.outputs = flatten(&g.tree("OUTPUT"))
                .iter()
                .map(|o| Output {
                    name: o.name.clone(),
                    ty: Some(o.type_name.clone()),
                })
                .collect();
        }
        // Its settings, in brackets, as their menus show them; its arguments are its inputs
        node.settings = c.settings.iter().filter_map(setting_label).collect();
        let n = self.push(node);
        let mut position = 0;
        if let Some(v) = piped {
            let name = params.first().map(|p| p.name.clone()).unwrap_or_default();
            self.add_input(n, name, v);
            position += 1;
        }
        for a in &c.args {
            let v = self.expr(&a.value);
            let name = match &a.name {
                Some(name) => {
                    if local.is_some() {
                        name.clone()
                    } else if matches!(c.name.as_str(), "MixShader" | "AddShader")
                        && matches!(name.as_str(), "a" | "b")
                    {
                        // The keys text gives the two Shader inputs
                        "Shader".to_owned()
                    } else {
                        socket_label(name)
                    }
                }
                None => {
                    let name = params
                        .get(position)
                        .map(|p| p.name.clone())
                        .unwrap_or_default();
                    position += 1;
                    name
                }
            };
            self.add_input(n, name, v);
        }
        Val::Node(n)
    }

    /// The output `socket` of what `target` gives: a node's output of that
    /// name (made if the node has none yet), a Separate XYZ for `.x`, `.y`,
    /// `.z` of a value.
    fn member(&mut self, target: Val, socket: &str, line: usize) -> Val {
        let xyz = ["x", "y", "z"].iter().position(|s| *s == socket);
        match target {
            Val::Node(n) if self.nodes[n].category != Category::Group || xyz.is_none() => {
                if let Some(i) = self.output_named(n, socket) {
                    return Val::Out(n, i);
                }
                if let Some(i) = xyz {
                    let o = self.default_output(n);
                    return self.separated(n, o, i, line);
                }
                self.nodes[n].outputs.push(Output {
                    name: humanize(socket),
                    ty: None,
                });
                Val::Out(n, self.nodes[n].outputs.len() - 1)
            }
            Val::Node(n) => {
                if let Some(i) = self.output_named(n, socket) {
                    return Val::Out(n, i);
                }
                let o = self.default_output(n);
                self.separated(n, o, xyz.unwrap_or(0), line)
            }
            Val::Out(n, o) => match xyz {
                Some(i) => self.separated(n, o, i, line),
                None => Val::Out(n, o),
            },
            Val::Lit(s, ty) => Val::Lit(format!("{s}.{socket}"), ty),
        }
    }

    fn output_named(&self, n: usize, socket: &str) -> Option<usize> {
        self.nodes[n].outputs.iter().position(|o| {
            o.name == socket || base_node::ast::key(&o.name) == socket || humanize(socket) == o.name
        })
    }

    fn separated(&mut self, n: usize, o: usize, axis: usize, line: usize) -> Val {
        let s = match self.separate.get(&(n, o)) {
            Some(&s) => s,
            None => {
                let s = self.push(Node::new("Separate XYZ", Category::Converter, line));
                self.nodes[s].inputs.push(Input {
                    name: "Vector".into(),
                    ty: Some("Vector".into()),
                    value: None,
                    link: Some((n, o)),
                });
                for name in ["X", "Y", "Z"] {
                    self.nodes[s].outputs.push(Output {
                        name: name.into(),
                        ty: Some("Float".into()),
                    });
                }
                self.separate.insert((n, o), s);
                s
            }
        };
        Val::Out(s, axis)
    }

    /// The output a node gives where none is named: its first, made when
    /// it has none (named after its variable, typed like its first input
    /// when that is a Geometry).
    fn default_output(&mut self, n: usize) -> usize {
        if self.nodes[n].outputs.is_empty() {
            let node = &self.nodes[n];
            let geometry = node.category == Category::Geometry
                && node
                    .inputs
                    .first()
                    .is_some_and(|i| i.ty.as_deref() == Some("Geometry"));
            let ty = if geometry {
                Some("Geometry".to_owned())
            } else if node.category == Category::Input && node.inputs.is_empty() {
                implicit_type(&node.title)
            } else {
                None
            };
            let name = if geometry {
                "Geometry".to_owned()
            } else if ty.is_some() {
                node.title.clone()
            } else {
                node.hint.clone().unwrap_or_default()
            };
            self.nodes[n].outputs.push(Output { name, ty });
        }
        0
    }

    fn add_input(&mut self, n: usize, name: String, v: Val) {
        let i = self.nodes[n].inputs.len();
        self.nodes[n].inputs.push(Input {
            name,
            ty: None,
            value: None,
            link: None,
        });
        self.connect(n, i, v);
    }

    fn connect(&mut self, n: usize, i: usize, v: Val) {
        if i >= self.nodes[n].inputs.len() {
            self.nodes[n].inputs.resize(
                i + 1,
                Input {
                    name: String::new(),
                    ty: None,
                    value: None,
                    link: None,
                },
            );
        }
        let (link, value, ty) = match v {
            Val::Lit(s, ty) => (None, Some(s), ty.map(str::to_owned)),
            Val::Out(m, o) => (Some((m, o)), None, self.nodes[m].outputs[o].ty.clone()),
            Val::Node(m) => {
                let o = self.default_output(m);
                (Some((m, o)), None, self.nodes[m].outputs[o].ty.clone())
            }
        };
        let input = &mut self.nodes[n].inputs[i];
        input.link = link;
        input.value = value;
        if input.ty.is_none() {
            input.ty = ty;
        }
    }
}

fn value_node(v: &Val) -> Option<usize> {
    match v {
        Val::Out(n, _) | Val::Node(n) => Some(*n),
        Val::Lit(..) => None,
    }
}

/// A setting in brackets as the node shows it: an enum value as its menu
/// (`Multiply`), a checkbox ticked by its name (`Clamp` for `use_clamp:
/// true`), another value with its name (`Image: Bricks`). `_`, a box left
/// unticked, a tuple, a ramp or curves are not drawn.
fn setting_label(s: &Setting) -> Option<String> {
    let value = match &s.value {
        Expr::Ref(r) if r.name == "_" => return None,
        Expr::Ref(r) => return Some(sugar::enum_label(&r.name)),
        Expr::Bool(b) => {
            let name = s.name.as_deref()?;
            return b
                .value
                .then(|| humanize(name.strip_prefix("use_").unwrap_or(name)));
        }
        Expr::Number(n) => number(n.value, n.is_int),
        Expr::String(t) => t.value.clone(),
        Expr::Neg(n) => match &*n.value {
            Expr::Number(n) => format!("-{}", number(n.value, n.is_int)),
            _ => return None,
        },
        _ => return None,
    };
    Some(match &s.name {
        Some(name) => format!("{}: {value}", humanize(name)),
        None => value,
    })
}

fn arg_names(args: &[Arg]) -> Vec<String> {
    args.iter()
        .map(|a| a.name.clone().unwrap_or_default())
        .collect()
}

fn number(v: f64, is_int: bool) -> String {
    if is_int {
        format!("{}", v as i64)
    } else if v.is_nan() {
        "nan".to_string()
    } else if v.is_infinite() {
        format!("{v}")
    } else {
        let s = format!("{v}");
        if s.contains('.') || s.contains('e') {
            s
        } else {
            format!("{s}.0")
        }
    }
}

/// `SetPosition` → `Set Position`, `offset_scale` → `Offset Scale`, as
/// Blender writes node and socket names.
pub fn humanize(name: &str) -> String {
    if name.contains('_') || name.chars().next().is_some_and(char::is_lowercase) {
        return name
            .split('_')
            .filter(|w| !w.is_empty())
            .map(|w| {
                let mut c = w.chars();
                match c.next() {
                    Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
                    None => String::new(),
                }
            })
            .collect::<Vec<_>>()
            .join(" ");
    }
    let chars: Vec<char> = name.chars().collect();
    let mut out = String::new();
    for (i, &c) in chars.iter().enumerate() {
        if i > 0 && c.is_uppercase() {
            let prev = chars[i - 1];
            let next_lower = chars.get(i + 1).is_some_and(|n| n.is_lowercase());
            if prev.is_lowercase() || prev.is_ascii_digit() || (prev.is_uppercase() && next_lower) {
                out.push(' ');
            }
        }
        out.push(c);
    }
    out
}

/// A color of the text (`#slategray`, `#ff8800`) as CSS; none when it
/// holds anything else.
fn css_color(c: &str) -> Option<String> {
    let c = c.trim_start_matches('#');
    if c.is_empty() || !c.chars().all(|ch| ch.is_ascii_alphanumeric()) {
        return None;
    }
    let hex = c.chars().all(|ch| ch.is_ascii_hexdigit()) && matches!(c.len(), 3 | 6 | 8);
    Some(if hex { format!("#{c}") } else { c.to_owned() })
}

/// A socket's name as Blender shows it: `value_001` is the second
/// `Value`, `offset_scale` is `Offset Scale`.
fn socket_label(key: &str) -> String {
    let base = match key.rsplit_once('_') {
        Some((base, n))
            if !base.is_empty() && n.len() == 3 && n.chars().all(|c| c.is_ascii_digit()) =>
        {
            base
        }
        _ => key,
    };
    humanize(base)
}

/// A node's category from its name alone, like Blender's node classes.
fn category(name: &str) -> Category {
    if name.chars().next().is_some_and(|c| c.is_lowercase()) || name.contains("::") {
        return Category::Group;
    }
    const INPUTS: &[&str] = &[
        "Position",
        "Normal",
        "Index",
        "ID",
        "Value",
        "Integer",
        "Boolean",
        "Vector",
        "RGB",
        "String",
        "SceneTime",
        "ObjectInfo",
        "CollectionInfo",
        "SelfObject",
        "Radius",
        "SplineParameter",
        "CurveTangent",
        "NamedAttribute",
        "TexCoord",
        "TextureCoordinate",
        "Time",
        "Frame",
        "Image",
        "Material",
        "Object",
        "Collection",
    ];
    const CONVERTERS: &[&str] = &[
        "Math",
        "VectorMath",
        "Compare",
        "BooleanMath",
        "Switch",
        "Mix",
        "MapRange",
        "Clamp",
        "CombineXYZ",
        "SeparateXYZ",
        "CombineColor",
        "SeparateColor",
        "FloatCurve",
        "ColorRamp",
        "FloatToInteger",
        "IntegerMath",
        "RandomValue",
        "AlignRotationToVector",
        "AxisAngleToRotation",
        "EulerToRotation",
        "RotationToEuler",
        "VectorRotate",
        "RotateVector",
        "IndexSwitch",
        "MenuSwitch",
        "AccumulateField",
        "FieldAtIndex",
        "EvaluateAtIndex",
        "SampleIndex",
    ];
    if INPUTS.contains(&name) || name.ends_with("Input") || name.ends_with("Info") {
        Category::Input
    } else if name.ends_with("Texture") {
        Category::Texture
    } else if name.ends_with("BSDF") || name.ends_with("Shader") || name == "Emission" {
        Category::Shader
    } else if name.starts_with("Vector") || name == "Mapping" || name == "Bump" {
        Category::Vector
    } else if CONVERTERS.contains(&name) {
        Category::Converter
    } else if name.contains("Output") || name == "Viewer" {
        Category::Output
    } else {
        Category::Geometry
    }
}

fn implicit_type(title: &str) -> Option<String> {
    Some(
        match title {
            "Position" | "Normal" | "Vector" | "Curve Tangent" => "Vector",
            "Index" | "ID" | "Integer" => "Int",
            "Value" | "Radius" => "Float",
            "Boolean" => "Bool",
            "RGB" => "Color",
            "String" => "String",
            _ => return None,
        }
        .to_owned(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn build(src: &str) -> Vec<Tree> {
        trees(&base_node::parse(src, "t.bn").expect("parses"))
    }

    fn titles(t: &Tree) -> Vec<&str> {
        t.nodes.iter().map(|n| n.title.as_str()).collect()
    }

    #[test]
    fn a_call_per_node_a_link_per_argument() {
        let t = &build(
            "geometry graph relief(geometry: Geometry, height: Float = 0.4) -> Geometry {\n  h = length(Position()) * height\n  return SetPosition(geometry, offset: CombineXYZ(z: h))\n}\n",
        )[0];
        let at = |title: &str| t.nodes.iter().position(|n| n.title == title).unwrap();
        let mut sorted = titles(t);
        sorted.sort();
        assert_eq!(
            sorted,
            [
                "Combine XYZ",
                "Group Input",
                "Group Output",
                "Length",
                "Multiply",
                "Position",
                "Set Position"
            ]
        );
        let set = &t.nodes[at("Set Position")];
        assert_eq!(set.inputs[0].link, Some((0, 0)));
        assert_eq!(set.inputs[0].ty.as_deref(), Some("Geometry"));
        assert_eq!(set.inputs[1].name, "Offset");
        assert_eq!(set.outputs[0].ty.as_deref(), Some("Geometry"));
        let mul = &t.nodes[at("Multiply")];
        assert_eq!(mul.inputs[1].link, Some((0, 1)));
        let out = t.nodes.last().unwrap();
        assert_eq!(out.inputs[0].link, Some((at("Set Position"), 0)));
    }

    #[test]
    fn literals_stay_in_their_input() {
        let t = &build(
            "geometry graph g() -> Geometry {\n  return MeshGrid(size_x: 2.0, vertices_x: 10)\n}\n",
        )[0];
        let grid = &t.nodes[0];
        assert_eq!(grid.inputs[0].value.as_deref(), Some("2.0"));
        assert_eq!(grid.inputs[1].value.as_deref(), Some("10"));
        assert!(grid.inputs.iter().all(|i| i.link.is_none()));
    }

    #[test]
    fn a_literal_is_shown_as_written() {
        let t = &build(
            "geometry graph g() -> Geometry {\n  return MeshGrid(size_x: -inf, size_y: nan) |> SetID(id: \"a \\\"b\\\"\\n\")\n}\n",
        )[0];
        let values: Vec<_> = t
            .nodes
            .iter()
            .flat_map(|n| n.inputs.iter().filter_map(|i| i.value.as_deref()))
            .collect();
        assert!(
            values.contains(&"-inf") && values.contains(&"nan"),
            "{values:?}"
        );
        assert!(values.contains(&r#""a \"b\"\n""#), "{values:?}");
    }

    #[test]
    fn a_member_of_a_vector_is_a_separate_xyz_made_once() {
        let t =
            &build("geometry graph g() -> Float {\n  p = Position()\n  return p.x + p.y\n}\n")[0];
        assert_eq!(
            titles(t).iter().filter(|s| **s == "Separate XYZ").count(),
            1
        );
    }

    #[test]
    fn frames_hold_their_statements_nodes() {
        let t = &build(
            "geometry graph g() -> Geometry {\n  \"Base\" #slategray {\n    m = MeshCube()\n  }\n  return m\n}\n",
        )[0];
        assert_eq!(t.frames[0].label, "Base");
        assert_eq!(t.frames[0].color.as_deref(), Some("slategray"));
        assert_eq!(t.nodes[0].frame, Some(0));
    }

    #[test]
    fn unused_variables_still_make_nodes() {
        let t = &build(
            "geometry graph g() -> Geometry {\n  unused = MeshCube()\n  return MeshCone()\n}\n",
        )[0];
        assert!(titles(t).contains(&"Mesh Cube"));
    }

    /// A node as drawn: its title, settings, input and output names.
    type Drawn = (String, Vec<String>, Vec<String>, Vec<String>);

    fn drawn(t: &Tree) -> Vec<Drawn> {
        t.nodes
            .iter()
            .map(|n| {
                (
                    n.title.clone(),
                    n.settings.clone(),
                    n.inputs.iter().map(|i| i.name.clone()).collect(),
                    n.outputs.iter().map(|o| o.name.clone()).collect(),
                )
            })
            .collect()
    }

    #[test]
    fn sugar_draws_the_node_it_writes() {
        let sugar =
            &build("geometry graph g(a: Float, b: Float) -> Float {\n  return a * b\n}\n")[0];
        let explicit = &build(
            "geometry graph g(a: Float, b: Float) -> Float {\n  return Math[MULTIPLY](value: a, value_001: b)\n}\n",
        )[0];
        assert_eq!(drawn(sugar), drawn(explicit));
        let math = &sugar.nodes[1];
        assert_eq!(math.title, "Multiply");
        assert_eq!(math.settings, ["Multiply"]);
        let names: Vec<&str> = math.inputs.iter().map(|i| i.name.as_str()).collect();
        assert_eq!(names, ["Value", "Value"]);
        assert_eq!(math.outputs[0].name, "Value");
    }

    #[test]
    fn smooth_min_and_the_keys_of_mix_shader() {
        let t = &build(
            "geometry graph g(a: Float, b: Float) -> Float {\n  return smooth_min(a, b, 0.25)\n}\n",
        )[0];
        let math = &t.nodes[1];
        assert_eq!(math.title, "Smooth Minimum");
        let names: Vec<&str> = math.inputs.iter().map(|i| i.name.as_str()).collect();
        assert_eq!(names, ["Value", "Value", "Distance"]);
        let t = &build(
            "shader graph g(f: Float) -> Shader {\n  return MixShader(factor: f, a: DiffuseBSDF(), b: Emission())\n}\n",
        )[0];
        let mix = t.nodes.iter().find(|n| n.title == "Mix Shader").unwrap();
        let names: Vec<&str> = mix.inputs.iter().map(|i| i.name.as_str()).collect();
        assert_eq!(names, ["Factor", "Shader", "Shader"]);
    }

    #[test]
    fn a_comparison_is_math_in_a_shader_tree() {
        let t = &build("shader graph g(a: Float, b: Float) -> Float {\n  return a > b\n}\n")[0];
        let titles: Vec<&str> = t.nodes[1..].iter().map(|n| n.title.as_str()).collect();
        assert_eq!(titles, ["Greater Than", "Group Output"]);
        assert_eq!(t.nodes[1].outputs[0].ty.as_deref(), Some("Float"));
        let t = &build("shader graph g(a: Float, b: Float) -> Float {\n  return a != b\n}\n")[0];
        let titles: Vec<&str> = t.nodes[1..].iter().map(|n| n.title.as_str()).collect();
        assert_eq!(titles, ["Compare", "Subtract", "Group Output"]);
        let names: Vec<&str> = t.nodes[1].inputs.iter().map(|i| i.name.as_str()).collect();
        assert_eq!(names, ["Value", "Value", "Epsilon"]);
        assert_eq!(t.nodes[1].inputs[2].value.as_deref(), Some("0.001"));
        assert_eq!(t.nodes[2].inputs[0].value.as_deref(), Some("1.0"));
        assert!(t.nodes[2].inputs[1].link.is_some());
    }

    #[test]
    fn a_ternary_draws_the_node_it_writes() {
        let t =
            &build("geometry graph g(on: Bool, a: Float) -> Float {\n  return on ? a : 0.0\n}\n")
                [0];
        let explicit = &build(
            "geometry graph g(on: Bool, a: Float) -> Float {\n  return Switch(switch: on, false_: 0.0, true_: a)\n}\n",
        )[0];
        assert_eq!(t.nodes[1].title, "Switch");
        assert_eq!(drawn(t), drawn(explicit));
        assert_eq!(t.nodes[1].inputs[1].value.as_deref(), Some("0.0"));
        // Where a Switch takes one value for a whole image, a Mix by the condition
        for kind in ["shader", "compositor"] {
            let t = &build(&format!(
                "{kind} graph g(a: Float, b: Float) -> Float {{\n  return a > b ? a : b\n}}\n"
            ))[0];
            let explicit = &build(&format!(
                "{kind} graph g(a: Float, b: Float) -> Float {{\n  return Mix(factor: a > b, a: b, b: a)\n}}\n"
            ))[0];
            assert_eq!(t.nodes[1].title, "Mix");
            assert_eq!(drawn(t), drawn(explicit));
        }
        let t = &build(
            "shader graph g(a: Float) -> Shader {\n  return a > 0.5 ? DiffuseBSDF() : Emission()\n}\n",
        )[0];
        let explicit = &build(
            "shader graph g(a: Float) -> Shader {\n  return MixShader(factor: a > 0.5, a: Emission(), b: DiffuseBSDF())\n}\n",
        )[0];
        let mut titles: Vec<String> = drawn(t).into_iter().map(|d| d.0).collect();
        let mut wanted: Vec<String> = drawn(explicit).into_iter().map(|d| d.0).collect();
        titles.sort();
        wanted.sort();
        assert_eq!(titles, wanted);
        assert!(titles.contains(&"Mix Shader".to_owned()));
    }

    #[test]
    fn a_comparison_is_a_compare_node() {
        let t = &build("geometry graph g(n: Int) -> Bool {\n  return n == 1\n}\n")[0];
        let cmp = &t.nodes[1];
        assert_eq!(cmp.title, "Equal");
        assert_eq!(cmp.settings, ["Integer", "Equal"]);
        let names: Vec<&str> = cmp.inputs.iter().map(|i| i.name.as_str()).collect();
        assert_eq!(names, ["A", "B"]);
        assert_eq!(cmp.outputs[0].name, "Result");
        let explicit = &build(
            "geometry graph g(n: Int) -> Bool {\n  return Compare[EQUAL, INT](a: n, b: 1)\n}\n",
        )[0];
        assert_eq!(drawn(t), drawn(explicit));
        // By name, the same node
        let named = &build(
            "geometry graph g(n: Int) -> Bool {\n  return Compare[operation: EQUAL, data_type: INT](a: n, b: 1)\n}\n",
        )[0];
        assert_eq!(drawn(t), drawn(named));
    }

    #[test]
    fn a_vector_times_a_number_scales_it() {
        let t = &build("geometry graph g() -> Vector {\n  return 2.0 * Position()\n}\n")[0];
        let scale = t
            .nodes
            .iter()
            .find(|n| n.title == "Scale")
            .expect("a Scale node");
        assert_eq!(scale.category, Category::Vector);
        assert_eq!(scale.inputs[0].name, "Vector");
        assert!(scale.inputs[0].link.is_some());
        assert_eq!(scale.inputs[1].value.as_deref(), Some("2.0"));
    }

    #[test]
    fn enum_properties_are_menus() {
        let t = &build(
            "geometry graph g() -> Geometry {\n  return MeshToPoints[FACES](MeshCube())\n}\n",
        )[0];
        let node = t
            .nodes
            .iter()
            .find(|n| n.title == "Mesh To Points")
            .unwrap();
        assert_eq!(node.settings, ["Faces"]);
        assert!(node.inputs.iter().all(|i| i.name != "Mode"));
    }

    #[test]
    fn settings_are_drawn_from_the_brackets_arguments_are_inputs() {
        let t = &build(
            "shader graph g(a: Float, b: Float) -> Float {\n  return Math[ADD, use_clamp: true](Value: a, Value_001: b)\n}\n",
        )[0];
        assert_eq!(t.nodes[1].title, "Add");
        assert_eq!(t.nodes[1].settings, ["Add", "Clamp"]);
        let t = &build(
            "shader graph g() -> Color {\n  return ImageTexture[Closest, image: \"Bricks\"](vector: TextureCoordinate().uv).color\n}\n",
        )[0];
        let node = t.nodes.iter().find(|n| n.title == "Image Texture").unwrap();
        assert_eq!(node.settings, ["Closest", "Image: Bricks"]);
        // An upper-case name in parentheses is an input, not a menu
        let t = &build(
            "geometry graph g(FACES: Float) -> Geometry {\n  return MeshToPoints(MeshCube(), radius: FACES)\n}\n",
        )[0];
        let node = t
            .nodes
            .iter()
            .find(|n| n.title == "Mesh To Points")
            .unwrap();
        assert!(node.settings.is_empty());
        assert!(node.inputs.iter().any(|i| i.name == "Radius"));
    }

    #[test]
    fn the_domain_of_a_foreach_is_on_its_input() {
        let t = &build(
            "geometry graph g(geometry: Geometry) -> Geometry {\n  r = foreach[FACE](geometry, item: 1.0) -> {\n    return (item: item)\n  }\n  return geometry\n}\n",
        )[0];
        let input = t
            .nodes
            .iter()
            .find(|n| n.title == "For Each Element Input")
            .unwrap();
        assert_eq!(input.settings, ["Face"]);
        assert!(input.inputs.iter().all(|i| i.name != "Domain"));
    }

    #[test]
    fn humanized_like_blender() {
        assert_eq!(humanize("SetPosition"), "Set Position");
        assert_eq!(humanize("CombineXYZ"), "Combine XYZ");
        assert_eq!(humanize("offset_scale"), "Offset Scale");
        assert_eq!(humanize("BSDFPrincipled"), "BSDF Principled");
    }
}
