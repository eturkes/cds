/**
 * `OnionLIRTree` — TS mirror of `crates/kernel/src/schema/onionl.rs`.
 *
 * Discriminated union with `kind` literal narrowing. The Rust enum uses
 * `#[serde(tag = "kind", rename_all = "snake_case")]` so the wire shape
 * carries `kind: "scope" | "relation" | "indicator_constraint" | "atom"`
 * for nodes and `kind: "variable" | "constant"` for terms.
 */

import { asArray, asInt, asLiteral, asObject, asString } from './parse';

export interface SourceSpan {
	start: number;
	end: number;
	doc_id: string;
}

export type Term = { kind: 'variable'; name: string } | { kind: 'constant'; value: string };

export type OnionLNode =
	| { kind: 'scope'; id: string; scope_kind: string; children: OnionLNode[] }
	| { kind: 'relation'; op: string; args: OnionLNode[] }
	| { kind: 'indicator_constraint'; guard: OnionLNode; body: OnionLNode }
	| {
			kind: 'atom';
			predicate: string;
			terms: Term[];
			source_span: SourceSpan;
	  };

export interface OnionLIRTree {
	schema_version: string;
	root: OnionLNode;
}

const NODE_KINDS = ['scope', 'relation', 'indicator_constraint', 'atom'] as const;
const TERM_KINDS = ['variable', 'constant'] as const;

function parseSourceSpan(value: unknown, path: string): SourceSpan {
	const obj = asObject(value, path);
	return {
		start: asInt(obj.start, `${path}.start`),
		end: asInt(obj.end, `${path}.end`),
		doc_id: asString(obj.doc_id, `${path}.doc_id`)
	};
}

function parseTerm(value: unknown, path: string): Term {
	const obj = asObject(value, path);
	const kind = asLiteral(obj.kind, `${path}.kind`, TERM_KINDS);
	if (kind === 'variable') {
		return { kind, name: asString(obj.name, `${path}.name`) };
	}
	return { kind, value: asString(obj.value, `${path}.value`) };
}

function parseNode(value: unknown, path: string): OnionLNode {
	const obj = asObject(value, path);
	const kind = asLiteral(obj.kind, `${path}.kind`, NODE_KINDS);
	switch (kind) {
		case 'scope':
			return {
				kind,
				id: asString(obj.id, `${path}.id`),
				scope_kind: asString(obj.scope_kind, `${path}.scope_kind`),
				children: asArray(obj.children, `${path}.children`, parseNode)
			};
		case 'relation':
			return {
				kind,
				op: asString(obj.op, `${path}.op`),
				args: asArray(obj.args, `${path}.args`, parseNode)
			};
		case 'indicator_constraint':
			return {
				kind,
				guard: parseNode(obj.guard, `${path}.guard`),
				body: parseNode(obj.body, `${path}.body`)
			};
		case 'atom':
			return {
				kind,
				predicate: asString(obj.predicate, `${path}.predicate`),
				terms: asArray(obj.terms, `${path}.terms`, parseTerm),
				source_span: parseSourceSpan(obj.source_span, `${path}.source_span`)
			};
	}
}

export function parseOnionLIRTree(value: unknown): OnionLIRTree {
	const obj = asObject(value, 'OnionLIRTree');
	return {
		schema_version: asString(obj.schema_version, 'OnionLIRTree.schema_version'),
		root: parseNode(obj.root, 'OnionLIRTree.root')
	};
}
