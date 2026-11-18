use std::collections::{HashMap, HashSet};

use crate::ast::*;
use crate::errors::BnError;
use crate::lexer::tokenize;
use crate::parser::parse;
use crate::tokens::TokenKind;

const INDENT: &str = "  ";
const WIDTH: usize = 100;

fn char_len(s: &str) -> usize {
    s.chars().count()
}

fn precedence(op: &str) -> usize {
    match op {
        "|>" => 1,
        "or" | "xor" => 2,
        "and" => 3,
        "not" => 4,
        "<" | "<=" | ">" | ">=" | "==" | "!=" => 5,
        "+" | "-" => 6,
        "*" | "/" | "⋅" | "×" => 7,
        _ => 0,
    }
}

pub fn format_source(source: &str, filename: &str) -> Result<String, BnError> {
    let file = parse(source, filename)?;
    let rows: Vec<&str> = source.split('\n').collect();

    let all_tokens = tokenize(source, filename, false)?;
    let comments: Vec<_> = all_tokens
        .into_iter()
        .filter(|t| t.kind == TokenKind::Comment)
        .collect();

    let mut alone = HashSet::new();
    for c in &comments {
        if c.line <= rows.len() {
            let row = rows[c.line - 1];
            let prefix: String = row.chars().take(c.col - 1).collect();
            if prefix.trim().is_empty() {
                alone.insert(c.line);
            }
        }
    }

    let mut printed: Vec<(usize, String, bool)> = Vec::new();

    fn walk(
        statements: &[Stmt],
        pad: &str,
        alone: &HashSet<usize>,
        printed: &mut Vec<(usize, String, bool)>,
    ) {
        for s in statements {
            match s {
                Stmt::Frame(f) => {
                    let has_alone = alone.iter().any(|&n| f.line < n && n < f.end);
                    if !f.body.is_empty() || has_alone {
                        printed.push((f.line, format!("{}{}", pad, frame_head(f)), true));
                        let inner_pad = format!("{}{}", pad, INDENT);
                        walk(&f.body, &inner_pad, alone, printed);
                        printed.push((f.end, format!("{}}}", pad), false));
                    } else {
                        let lines = format_statement(s, pad);
                        for (k, (o, t)) in lines.into_iter().enumerate() {
                            printed.push((o, t, k == 0));
                        }
                    }
                }
                Stmt::Assign(a) => match &a.value {
                    AssignValue::Repeat(_)
                    | AssignValue::Closure(_)
                    | AssignValue::Simulate(_)
                    | AssignValue::Foreach(_) => {
                        let head_lines = zone_head(&a.name, &a.value, pad, a.line);
                        for (k, (o, t)) in head_lines.into_iter().enumerate() {
                            printed.push((o, t, k == 0));
                        }
                        let inner_body = match &a.value {
                            AssignValue::Repeat(r) => &r.body,
                            AssignValue::Closure(c) => &c.body,
                            AssignValue::Simulate(s) => &s.body,
                            AssignValue::Foreach(f) => &f.body,
                            _ => unreachable!(),
                        };
                        let end = match &a.value {
                            AssignValue::Repeat(r) => r.end,
                            AssignValue::Closure(c) => c.end,
                            AssignValue::Simulate(s) => s.end,
                            AssignValue::Foreach(f) => f.end,
                            _ => unreachable!(),
                        };
                        let inner_pad = format!("{}{}", pad, INDENT);
                        walk(inner_body, &inner_pad, alone, printed);
                        printed.push((end, format!("{}}}", pad), false));
                    }
                    AssignValue::Expr(_) => {
                        let lines = format_statement(s, pad);
                        for (k, (o, t)) in lines.into_iter().enumerate() {
                            printed.push((o, t, k == 0));
                        }
                    }
                },
                Stmt::Return(_) => {
                    let lines = format_statement(s, pad);
                    for (k, (o, t)) in lines.into_iter().enumerate() {
                        printed.push((o, t, k == 0));
                    }
                }
            }
        }
    }

    // Sorted uses
    let sorted = sorted_uses(&file.uses);
    for u in &sorted {
        let lines = format_use(u);
        for (k, (o, t)) in lines.into_iter().enumerate() {
            printed.push((o, t, k == 0));
        }
    }
    if !file.uses.is_empty() {
        let max_line = file.uses.iter().map(|u| u.line).max().unwrap_or(1);
        printed.push((max_line, String::new(), false));
    }

    for (i, g) in file.graphs.iter().enumerate() {
        if i > 0 {
            printed.push((file.graphs[i - 1].end, String::new(), false));
        }
        let head_lines = format_header(g);
        for (k, (o, t)) in head_lines.into_iter().enumerate() {
            printed.push((o, t, k == 0));
        }
        if let Some(ref desc) = g.description {
            printed.push((
                g.description_line,
                format!("{}{}", INDENT, quote(desc)),
                true,
            ));
        }
        walk(&g.body, INDENT, &alone, &mut printed);
        printed.push((g.end, "}".to_string(), false));
    }

    let mut own = Vec::new();
    let mut trailing: HashMap<usize, Vec<String>> = HashMap::new();

    for c in &comments {
        let text = c.text.trim_end().to_string();
        if !alone.contains(&c.line) {
            let on: Vec<usize> = printed
                .iter()
                .enumerate()
                .filter(|(_, (o, t, _))| *o == c.line && !t.is_empty())
                .map(|(k, _)| k)
                .collect();
            let at = if !on.is_empty() {
                *on.last().unwrap()
            } else {
                let candidates: Vec<usize> = printed
                    .iter()
                    .enumerate()
                    .filter(|(_, (o, t, _))| *o <= c.line && !t.is_empty())
                    .map(|(k, _)| k)
                    .collect();
                if candidates.is_empty() {
                    0
                } else {
                    *candidates.last().unwrap()
                }
            };
            trailing.entry(at).or_default().push(text);
        } else {
            own.push((c.line, text));
        }
    }

    let mut out: Vec<String> = Vec::new();

    let blank_fn = |line: usize| -> bool {
        1 <= line && line <= rows.len() && rows[line - 1].trim().is_empty()
    };

    let mut emit = |origin: usize, text: String, starts: bool| {
        if starts
            && !out.is_empty()
            && !out.last().unwrap().is_empty()
            && !out.last().unwrap().ends_with('{')
            && blank_fn(origin - 1)
        {
            out.push(String::new());
        }
        out.push(text);
    };

    let mut j = 0;
    for (k, (origin, text, starts)) in printed.into_iter().enumerate() {
        while j < own.len() && own[j].0 < origin {
            let (line, comment) = &own[j];
            emit(*line, format!("{}{}", indent(&text), comment), true);
            j += 1;
        }
        let line_text = if let Some(tr) = trailing.get(&k) {
            let mut parts = vec![text];
            parts.extend(tr.clone());
            parts.join("  ")
        } else {
            text
        };
        emit(origin, line_text, starts);
    }

    while j < own.len() {
        let (line, comment) = &own[j];
        emit(*line, comment.clone(), true);
        j += 1;
    }

    let mut result = out.join("\n");
    result.push('\n');
    Ok(result)
}

fn indent(text: &str) -> String {
    let stripped = text.trim_start();
    let pad_len = text.len() - stripped.len();
    let pad = &text[..pad_len];
    if stripped == "}" {
        format!("{}{}", pad, INDENT)
    } else {
        pad.to_string()
    }
}

pub fn format_file(file: &File) -> String {
    let mut parts = Vec::new();
    let head = sorted_uses(&file.uses)
        .iter()
        .flat_map(format_use)
        .map(|(_, t)| format!("{}\n", t))
        .collect::<String>();
    if !head.is_empty() {
        parts.push(head);
    }
    let graphs = file
        .graphs
        .iter()
        .map(|g| {
            let mut lines = format_header(g);
            if let Some(ref desc) = g.description {
                lines.push((g.description_line, format!("{}{}", INDENT, quote(desc))));
            }
            for s in &g.body {
                lines.extend(format_statement(s, INDENT));
            }
            lines.push((g.end, "}".to_string()));
            lines
                .into_iter()
                .map(|(_, t)| format!("{}\n", t))
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join("\n");
    parts.push(graphs);
    parts.join("\n")
}

fn sorted_uses(uses: &[Use]) -> Vec<Use> {
    let mut out = uses.to_vec();
    out.sort_by(|a, b| {
        a.name.cmp(&b.name).then_with(|| {
            a.source
                .as_deref()
                .unwrap_or("")
                .cmp(b.source.as_deref().unwrap_or(""))
        })
    });
    out
}

fn format_use(u: &Use) -> Vec<(usize, String)> {
    let tail = if let Some(ref src) = u.source {
        format!(" from {}", quote(src))
    } else {
        String::new()
    };
    let alias_str = if let Some(ref alias) = u.alias {
        format!(" as {}", alias)
    } else {
        String::new()
    };
    let names_str = if let Some(ref names) = u.names {
        format!(" ({})", names.join(", "))
    } else {
        String::new()
    };
    let line = format!("use {}{}{}{}", u.name, alias_str, names_str, tail);
    if char_len(&line) <= WIDTH || u.names.is_none() {
        return vec![(u.line, line)];
    }
    let mut lines = vec![(u.line, format!("use {}{} (", u.name, alias_str))];
    if let Some(ref names) = u.names {
        for n in names {
            lines.push((u.line, format!("{}{},", INDENT, n)));
        }
    }
    lines.push((u.line, format!("){}", tail)));
    lines
}

fn format_header(g: &Graph) -> Vec<(usize, String)> {
    let lead_settings = if !g.settings.is_empty() {
        format!("({})", format_args(&g.settings))
    } else {
        String::new()
    };
    let lead = format!(
        "{}{lead_settings} graph {}{}",
        g.kind,
        name_display(&g.name),
        type_params(g)
    );
    let params: Vec<String> = g.params.iter().map(format_param).collect();
    let outputs = if g.single_output {
        g.outputs[0].type_name.clone()
    } else {
        format!(
            "({})",
            g.outputs
                .iter()
                .map(format_param)
                .collect::<Vec<_>>()
                .join(", ")
        )
    };
    let head = format!("{lead}({}) -> {} {{", params.join(", "), outputs);
    let paneled = (g.param_tree.is_some(), g.output_tree.is_some());
    if char_len(&head) <= WIDTH && !paneled.0 && !paneled.1 {
        return vec![(g.line, head)];
    }

    let mut lines = Vec::new();
    if !params.is_empty() || paneled.0 {
        let ins = g.tree("INPUT");
        let ins_last = last_line(&ins);
        lines.push((g.line, format!("{lead}(")));
        lines.extend(one_per_line(&ins, &format!("{}{}", INDENT, INDENT)));
        lines.push((ins_last, format!(") -> {} {{", outputs)));
    } else {
        lines.push((g.line, format!("{lead}() -> {} {{", outputs)));
    }

    if (char_len(&lines.last().unwrap().1) <= WIDTH && !paneled.1) || g.single_output {
        return lines;
    }

    let close = if lines.len() > 1 {
        ") -> (".to_string()
    } else {
        format!("{lead}() -> (")
    };
    let outs = g.tree("OUTPUT");
    let outs_last = last_line(&outs);
    let last_idx = lines.len() - 1;
    lines[last_idx].1 = close;
    lines.extend(one_per_line(&outs, &format!("{}{}", INDENT, INDENT)));
    lines.push((outs_last, ") {".to_string()));
    lines
}

fn one_per_line(items: &[ParamTreeItem], pad: &str) -> Vec<(usize, String)> {
    let mut lines = Vec::new();
    for i in items {
        match i {
            ParamTreeItem::Panel(p) => {
                let opt_str = if p.options.is_empty() {
                    String::new()
                } else {
                    format!("({})", format_args(&p.options))
                };
                let close = if p.items.is_empty() { " {}," } else { " {" };
                let head = format!("{}{}{}{}", pad, quote(&p.name), opt_str, close);
                if char_len(&head) > WIDTH && !p.options.is_empty() {
                    let open = format!("{}{}(", pad, quote(&p.name));
                    lines.extend(spread(
                        &open,
                        &p.options,
                        p.line,
                        pad,
                        &format!("){}", close),
                    ));
                } else {
                    lines.push((p.line, head));
                }
                if !p.items.is_empty() {
                    let inner_pad = format!("{}{}{}", pad, INDENT, INDENT);
                    lines.extend(one_per_line(&p.items, &inner_pad));
                    lines.push((p.end, format!("{}}},", pad)));
                }
            }
            ParamTreeItem::Param(p) => {
                lines.extend(param_lines(p, pad, ","));
            }
        }
    }
    if let Some(last) = lines.last_mut() {
        last.1.pop(); // remove trailing comma
    }
    lines
}

fn last_line(items: &[ParamTreeItem]) -> usize {
    if let Some(last) = items.last() {
        match last {
            ParamTreeItem::Panel(p) => p.end,
            ParamTreeItem::Param(p) => p.line,
        }
    } else {
        0
    }
}

pub fn format_param(p: &Param) -> String {
    let options = if p.options.is_empty() {
        String::new()
    } else {
        format!("({})", format_args(&p.options))
    };
    format!("{}{}{}", param_head(p), options, param_rest(p))
}

fn param_head(p: &Param) -> String {
    let alias = p
        .alias
        .as_ref()
        .map(|a| format!(" as {}", a))
        .unwrap_or_default();
    format!("{}{}: {}", name_display(&p.name), alias, p.type_name)
}

/// A param on a line of its own at `pad`; its options one per line when it is too long.
fn param_lines(p: &Param, pad: &str, tail: &str) -> Vec<(usize, String)> {
    let flat = format!("{}{}{}", pad, format_param(p), tail);
    if char_len(&flat) <= WIDTH || p.options.is_empty() {
        return vec![(p.line, flat)];
    }
    let head = format!("{}{}(", pad, param_head(p));
    spread(
        &head,
        &p.options,
        p.line,
        pad,
        &format!("){}{}", param_rest(p), tail),
    )
}

/// What follows a param's type and options: its default and its range.
fn param_rest(p: &Param) -> String {
    let mut text = String::new();
    if let Some(ref default) = p.default {
        text.push_str(&format!(" = {}", format_expr(default, 0)));
    }
    if let Some(ref range) = p.range {
        let lo = range
            .0
            .as_ref()
            .map(|b| format_expr(b, 0))
            .unwrap_or_default();
        let hi = range
            .1
            .as_ref()
            .map(|b| format_expr(b, 0))
            .unwrap_or_default();
        text.push_str(&format!(" in {}..{}", lo, hi));
    }
    text
}

pub fn format_statement(s: &Stmt, pad: &str) -> Vec<(usize, String)> {
    match s {
        Stmt::Frame(f) => {
            let head = frame_head(f);
            if f.body.is_empty() {
                return vec![(f.line, format!("{}{}}}", pad, head))];
            }
            let mut lines = vec![(f.line, format!("{}{}", pad, head))];
            let inner_pad = format!("{}{}", pad, INDENT);
            for inner in &f.body {
                lines.extend(format_statement(inner, &inner_pad));
            }
            lines.push((f.end, format!("{}}}", pad)));
            lines
        }
        Stmt::Assign(a) => match &a.value {
            AssignValue::Repeat(_)
            | AssignValue::Closure(_)
            | AssignValue::Simulate(_)
            | AssignValue::Foreach(_) => {
                let mut lines = zone_head(&a.name, &a.value, pad, a.line);
                let inner_body = match &a.value {
                    AssignValue::Repeat(r) => &r.body,
                    AssignValue::Closure(c) => &c.body,
                    AssignValue::Simulate(s) => &s.body,
                    AssignValue::Foreach(f) => &f.body,
                    _ => unreachable!(),
                };
                let end = match &a.value {
                    AssignValue::Repeat(r) => r.end,
                    AssignValue::Closure(c) => c.end,
                    AssignValue::Simulate(s) => s.end,
                    AssignValue::Foreach(f) => f.end,
                    _ => unreachable!(),
                };
                let inner_pad = format!("{}{}", pad, INDENT);
                for inner in inner_body {
                    lines.extend(format_statement(inner, &inner_pad));
                }
                lines.push((end, format!("{}}}", pad)));
                lines
            }
            AssignValue::Expr(e) => {
                let lead = format!("{}{} = ", pad, a.name);
                value(&lead, e, a.line, pad, &look_tail(a.look.as_ref()))
            }
        },
        Stmt::Return(r) => {
            let tail = look_tail(r.look.as_ref());
            match &r.value {
                ReturnValue::Record(rec) => {
                    let line = format!("{}return ({}){}", pad, format_args(&rec.fields), tail);
                    if char_len(&line) <= WIDTH || rec.fields.is_empty() {
                        vec![(r.line, line)]
                    } else {
                        let lead = format!("{}return (", pad);
                        spread(&lead, &rec.fields, r.line, pad, &format!("){}", tail))
                    }
                }
                ReturnValue::Expr(e) => {
                    let lead = format!("{}return ", pad);
                    value(&lead, e, r.line, pad, &tail)
                }
            }
        }
    }
}

/// A statement's look (`@ mute`) as the tail of its last line, or nothing.
fn look_tail(look: Option<&Look>) -> String {
    look.map(|l| format!(" {}", look_text(l)))
        .unwrap_or_default()
}

fn look_text(look: &Look) -> String {
    let mut parts = vec!["@".to_string()];
    if let Some(ref label) = look.label {
        parts.push(quote(label));
    }
    if let Some(ref color) = look.color {
        parts.push(color.clone());
    }
    for f in &look.flags {
        parts.push(f.clone());
    }
    parts.join(" ")
}

fn zone_head(name: &str, z: &AssignValue, pad: &str, _assign_line: usize) -> Vec<(usize, String)> {
    match z {
        AssignValue::Closure(c) => closure_head(name, c, pad),
        AssignValue::Repeat(r) => {
            let mut items = vec![Arg {
                name: None,
                value: r.count.clone(),
                line: r.line,
                col: r.col,
                options: Vec::new(),
                type_decl: None,
                alias: None,
            }];
            items.extend(r.states.clone());
            let line = format!("{}{} = repeat({}) {{", pad, name, format_args(&items));
            if char_len(&line) <= WIDTH || items.is_empty() {
                return vec![(r.line, line)];
            }
            spread(
                &format!("{}{} = repeat(", pad, name),
                &items,
                r.line,
                pad,
                ") {",
            )
        }
        AssignValue::Simulate(s) => {
            let line = format!("{}{} = simulate({}) {{", pad, name, format_args(&s.states));
            if char_len(&line) <= WIDTH || s.states.is_empty() {
                return vec![(s.line, line)];
            }
            spread(
                &format!("{}{} = simulate(", pad, name),
                &s.states,
                s.line,
                pad,
                ") {",
            )
        }
        AssignValue::Foreach(f) => {
            let mut items = vec![Arg {
                name: None,
                value: f.geometry.clone(),
                line: f.line,
                col: f.col,
                options: Vec::new(),
                type_decl: None,
                alias: None,
            }];
            items.extend(f.args.clone());
            let line = format!("{}{} = foreach({}) {{", pad, name, format_args(&items));
            if char_len(&line) <= WIDTH || items.is_empty() {
                return vec![(f.line, line)];
            }
            spread(
                &format!("{}{} = foreach(", pad, name),
                &items,
                f.line,
                pad,
                ") {",
            )
        }
        AssignValue::Expr(_) => unreachable!(),
    }
}

fn closure_head(name: &str, c: &Closure, pad: &str) -> Vec<(usize, String)> {
    let outs = signature_outputs(&c.outputs, c.single_output);
    let params_str = c
        .params
        .iter()
        .map(format_param)
        .collect::<Vec<_>>()
        .join(", ");
    let line = format!("{}{} = closure({}) -> {} {{", pad, name, params_str, outs);
    if char_len(&line) <= WIDTH || c.params.is_empty() {
        return vec![(c.line, line)];
    }
    let mut lines = vec![(c.line, format!("{}{} = closure(", pad, name))];
    let inner = format!("{}{}", pad, INDENT);
    for p in &c.params {
        lines.extend(param_lines(p, &inner, ","));
    }
    if let Some(last) = lines.last_mut() {
        last.1.pop(); // remove comma
    }
    lines.push((
        c.params.last().map(|p| p.line).unwrap_or(c.line),
        format!("{}) -> {} {{", pad, outs),
    ));
    lines
}

fn signature_outputs(outputs: &[Param], single: bool) -> String {
    if single {
        outputs[0].type_name.clone()
    } else {
        format!(
            "({})",
            outputs
                .iter()
                .map(format_param)
                .collect::<Vec<_>>()
                .join(", ")
        )
    }
}

fn frame_head(f: &Frame) -> String {
    let mut parts = Vec::new();
    if let Some(ref label) = f.label {
        parts.push(quote(label));
    }
    if f.continued {
        parts.push("..".to_string());
    } else if let Some(ref color) = f.color {
        parts.push(color.clone());
    }
    let mut s = String::new();
    for p in parts {
        s.push_str(&p);
        s.push(' ');
    }
    s.push('{');
    s
}

/// A statement's value after `lead`, `tail` (its look) at the end. A pipe always puts each
/// step on a line of its own; anything else stays on one line while it fits (`layout`).
fn value(lead: &str, e: &Expr, origin: usize, pad: &str, tail: &str) -> Vec<(usize, String)> {
    if let Expr::Pipe(_) = e {
        return piped(e, lead, pad, tail, origin);
    }
    layout(e, lead, pad, tail, 0, origin)
}

/// `lead`, `e` and `tail` as lines no wider than WIDTH where they can be.
///
/// On one line when it fits; else the outermost structure spreads, one item per line one
/// indent further in than `pad` (the indent of the line it starts on), and each of those
/// lines follows the same rule. `outer` is the binding strength around `e`, as in `format_expr`.
fn layout(
    e: &Expr,
    lead: &str,
    pad: &str,
    tail: &str,
    outer: usize,
    origin: usize,
) -> Vec<(usize, String)> {
    let flat = format!("{}{}{}", lead, format_expr(e, outer), tail);
    if char_len(&flat) <= WIDTH {
        return vec![(origin, flat)];
    }
    if parenthesized(e, outer) {
        return layout(
            e,
            &format!("{}(", lead),
            pad,
            &format!("){}", tail),
            0,
            origin,
        );
    }
    let inner = format!("{}{}", pad, INDENT);
    match e {
        Expr::Call(c) if !c.args.is_empty() => {
            let outputs = c
                .outputs
                .as_ref()
                .map(|o| format!(" -> {}", signature_outputs(o, c.single_output)))
                .unwrap_or_default();
            let head = format!("{}{}(", lead, callee(c));
            let mut lines = spread(
                &head,
                &c.args,
                origin,
                pad,
                &format!("){}{}", outputs, tail),
            );
            if let Some(outs) = c.outputs.as_ref() {
                let too_long = char_len(&lines.last().unwrap().1) > WIDTH;
                if too_long && !outs.is_empty() && !c.single_output {
                    // Declared outputs too long for the closing line: one per line as well
                    lines = spread(&head, &c.args, origin, pad, ") -> (");
                    for (i, o) in outs.iter().enumerate() {
                        let close = if i + 1 == outs.len() {
                            format!("){}", tail)
                        } else {
                            ",".to_string()
                        };
                        lines.extend(param_lines(o, &inner, &close));
                    }
                }
            }
            lines
        }
        Expr::Tuple(t) if !t.items.is_empty() => {
            let mut lines = vec![(origin, format!("{}(", lead))];
            for (i, item) in t.items.iter().enumerate() {
                let close = if i + 1 == t.items.len() {
                    format!("){}", tail)
                } else {
                    ",".to_string()
                };
                lines.extend(layout(item, &inner, &inner, &close, 0, item.line()));
            }
            lines
        }
        Expr::Member(m) => layout(
            &m.target,
            lead,
            pad,
            &format!(".{}{}", label_display(&m.socket), tail),
            9,
            origin,
        ),
        Expr::Pipe(_) => piped(e, lead, pad, tail, origin),
        Expr::BinOp(b) => chained(b, lead, pad, tail, origin),
        Expr::Neg(n) => layout(&n.value, &format!("{}-", lead), pad, tail, 9, origin),
        Expr::Not(n) => layout(
            &n.value,
            &format!("{}not ", lead),
            pad,
            tail,
            precedence("not"),
            origin,
        ),
        _ => vec![(origin, flat)],
    }
}

/// Whether `format_expr(e, outer)` puts `e` in parentheses.
fn parenthesized(e: &Expr, outer: usize) -> bool {
    match e {
        Expr::Call(c) => c.outputs.is_some() && outer >= 9,
        Expr::Neg(_) => outer > 8,
        Expr::Not(_) => outer > precedence("not"),
        Expr::BinOp(b) => precedence(&b.op) < outer,
        Expr::Pipe(_) => precedence("|>") < outer,
        _ => false,
    }
}

/// The head of a pipe after `lead`, then each step on a line of its own, one indent further in;
/// a head too long for its line spreads one indent further in than the steps.
fn piped(e: &Expr, lead: &str, pad: &str, tail: &str, origin: usize) -> Vec<(usize, String)> {
    let mut pipes = Vec::new();
    let mut cur = e;
    while let Expr::Pipe(p) = cur {
        pipes.push(p);
        cur = p.left.as_ref();
    }
    let p = precedence("|>");
    let step_pad = format!("{}{}", pad, INDENT);
    let mut lines = layout(cur, lead, &step_pad, "", p, origin);
    for (i, step) in pipes.iter().rev().enumerate() {
        let close = if i + 1 == pipes.len() { tail } else { "" };
        let step_lead = format!("{}|> ", step_pad);
        lines.extend(layout(
            &step.call,
            &step_lead,
            &step_pad,
            close,
            p + 1,
            step.line,
        ));
    }
    lines
}

/// The binding strength `format_expr` prints a BinOp's left operand with.
fn left_outer(b: &BinOp) -> usize {
    let p = precedence(&b.op);
    let mixed = match b.left.as_ref() {
        Expr::BinOp(left) => {
            left.op != b.op
                && (["⋅", "×", "xor"].contains(&b.op.as_str())
                    || ["⋅", "×", "xor"].contains(&left.op.as_str()))
        }
        _ => false,
    };
    if p == precedence("==") || mixed {
        p + 1
    } else {
        p
    }
}

/// A chain of operators of one strength: its first operand after `lead`, then each operator
/// with its operand on a line of its own, one indent further in (`+ b`); a first operand too long
/// for its line spreads one indent further in than the operators.
fn chained(b: &BinOp, lead: &str, pad: &str, tail: &str, origin: usize) -> Vec<(usize, String)> {
    let p = precedence(&b.op);
    let mut rest = Vec::new();
    let mut cur = b;
    loop {
        rest.push(cur);
        match cur.left.as_ref() {
            Expr::BinOp(left) if precedence(&left.op) == p && left_outer(cur) == p => cur = left,
            _ => break,
        }
    }
    let op_pad = format!("{}{}", pad, INDENT);
    let mut lines = layout(&cur.left, lead, &op_pad, "", left_outer(cur), origin);
    for (i, op) in rest.iter().rev().enumerate() {
        let close = if i + 1 == rest.len() { tail } else { "" };
        let op_lead = format!("{}{} ", op_pad, op.op);
        lines.extend(layout(&op.right, &op_lead, &op_pad, close, p + 1, op.line));
    }
    lines
}

/// `head` then one argument per line one indent further in, the last one ending with `close`.
fn spread(
    head: &str,
    items: &[Arg],
    origin: usize,
    pad: &str,
    close: &str,
) -> Vec<(usize, String)> {
    let inner = format!("{}{}", pad, INDENT);
    let mut lines = vec![(origin, head.to_string())];
    for (i, a) in items.iter().enumerate() {
        let tail = if i + 1 == items.len() { close } else { "," };
        lines.extend(argument(a, &inner, tail));
    }
    lines
}

/// An argument on a line of its own at `pad`, laid out like any value.
fn argument(a: &Arg, pad: &str, tail: &str) -> Vec<(usize, String)> {
    let Some(ref name) = a.name else {
        return layout(&a.value, pad, pad, tail, 0, a.line);
    };
    let alias = a
        .alias
        .as_ref()
        .map(|x| format!(" as {}", x))
        .unwrap_or_default();
    let options = if a.options.is_empty() {
        String::new()
    } else {
        format!("({})", format_args(&a.options))
    };
    let typed = a
        .type_decl
        .as_ref()
        .map(|t| format!("{} = ", t.type_name))
        .unwrap_or_default();
    let lead = format!(
        "{}{}{}{}: {}",
        pad,
        label_display(name),
        alias,
        options,
        typed
    );
    let flat = format!("{}{}{}", lead, format_expr(&a.value, 0), tail);
    if char_len(&flat) > WIDTH && !a.options.is_empty() {
        // Options first, one per line; the value after them, laid out from the line they end on
        let open = format!("{}{}{}(", pad, label_display(name), alias);
        let mut lines = spread(&open, &a.options, a.line, pad, &format!("): {}", typed));
        let (origin, last) = lines.pop().unwrap();
        let value_pad = format!("{}{}", pad, INDENT);
        lines.extend(layout(&a.value, &last, &value_pad, tail, 0, origin));
        return lines;
    }
    layout(&a.value, &lead, pad, tail, 0, a.line)
}

pub fn format_args(items: &[Arg]) -> String {
    items.iter().map(format_arg).collect::<Vec<_>>().join(", ")
}

pub fn format_arg(a: &Arg) -> String {
    if let Some(ref name) = a.name {
        let mut options = String::new();
        if let Some(ref alias) = a.alias {
            options.push_str(&format!(" as {}", alias));
        }
        if !a.options.is_empty() {
            options.push_str(&format!("({})", format_args(&a.options)));
        }
        if let Some(ref type_decl) = a.type_decl {
            format!(
                "{}{}: {} = {}",
                label_display(name),
                options,
                type_decl.type_name,
                format_expr(&a.value, 0)
            )
        } else {
            format!(
                "{}{}: {}",
                label_display(name),
                options,
                format_expr(&a.value, 0)
            )
        }
    } else {
        format_expr(&a.value, 0)
    }
}

/// A float as Python's `repr` spells it, so both printers write the same text: the shortest
/// digits that read back the same, with an exponent below 1e-4 and from 1e16 (`1e-05`, `1e+18`).
fn float_repr(v: f64) -> String {
    if v != 0.0 && v.is_finite() {
        let sci = format!("{:e}", v);
        if let Some((mantissa, exp)) = sci.split_once('e') {
            let exp: i32 = exp.parse().unwrap_or(0);
            if !(-4..16).contains(&exp) {
                let sign = if exp < 0 { '-' } else { '+' };
                return format!("{}e{}{:02}", mantissa, sign, exp.abs());
            }
        }
    }
    let mut s = format!("{}", v);
    if v.is_finite() && !s.contains('.') {
        s.push_str(".0");
    }
    s
}

pub fn format_expr(e: &Expr, outer: usize) -> String {
    match e {
        Expr::Number(num) => {
            if num.is_int {
                format!("{}", num.value as i64)
            } else {
                float_repr(num.value)
            }
        }
        Expr::String(s) => quote(&s.value),
        Expr::Bool(b) => {
            if b.value {
                "true".to_string()
            } else {
                "false".to_string()
            }
        }
        Expr::Tuple(t) => {
            format!(
                "({})",
                t.items
                    .iter()
                    .map(|i| format_expr(i, 0))
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        }
        Expr::Ref(r) => r.name.clone(),
        Expr::Member(m) => {
            format!("{}.{}", format_expr(&m.target, 9), label_display(&m.socket))
        }
        Expr::Call(c) => {
            if let Some(ref outs) = c.outputs {
                let text = format!(
                    "{}({}) -> {}",
                    callee(c),
                    format_args(&c.args),
                    signature_outputs(outs, c.single_output)
                );
                if outer >= 9 {
                    format!("({})", text)
                } else {
                    text
                }
            } else {
                format!("{}({})", callee(c), format_args(&c.args))
            }
        }
        Expr::Neg(neg) => {
            let text = format!("-{}", format_expr(&neg.value, 9));
            if outer > 8 {
                format!("({})", text)
            } else {
                text
            }
        }
        Expr::Not(not) => {
            let p = precedence("not");
            let text = format!("not {}", format_expr(&not.value, p));
            if outer > p {
                format!("({})", text)
            } else {
                text
            }
        }
        Expr::BinOp(b) => {
            let p = precedence(&b.op);
            let mixed = match b.left.as_ref() {
                Expr::BinOp(left_bin) => {
                    left_bin.op != b.op
                        && (["⋅", "×", "xor"].contains(&b.op.as_str())
                            || ["⋅", "×", "xor"].contains(&left_bin.op.as_str()))
                }
                _ => false,
            };
            let left_outer = if p == precedence("==") || mixed {
                p + 1
            } else {
                p
            };
            let left_str = format_expr(&b.left, left_outer);
            let right_str = format_expr(&b.right, p + 1);
            let text = format!("{} {} {}", left_str, b.op, right_str);
            if p < outer {
                format!("({})", text)
            } else {
                text
            }
        }
        Expr::Pipe(p) => {
            let prec = precedence("|>");
            let left_str = format_expr(&p.left, prec);
            let right_str = format_expr(&p.call, prec + 1);
            let text = format!("{} |> {}", left_str, right_str);
            if prec < outer {
                format!("({})", text)
            } else {
                text
            }
        }
    }
}

/// `<T: Float | Vector, U: Int | Float>` of a template, nothing for a graph.
fn type_params(g: &Graph) -> String {
    if g.type_params.is_empty() {
        return String::new();
    }
    let params: Vec<String> = g
        .type_params
        .iter()
        .map(|t| format!("{}: {}", t.name, t.types.join(" | ")))
        .collect();
    format!("<{}>", params.join(", "))
}

/// A call's name, with the types it is called with when written: `attribute_or<Vector>`.
fn callee(c: &Call) -> String {
    match c.type_args {
        Some(ref types) if !types.is_empty() => format!("{}<{}>", c.name, types.join(", ")),
        _ => c.name.clone(),
    }
}
