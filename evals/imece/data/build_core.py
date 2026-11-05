"""Curated contracts with explicit expected values; emits the frozen v1 suite.

Regeneration is an intentional suite-version change, never part of a live run.
Reference implementations here validate the harness, not model performance.
"""

import json
from pathlib import Path

# id, category, contract, reference body, (input, expected) pairs
TASKS = [
    (
        "stable_unique",
        "code",
        "Input: list of integers. Return first occurrences in original order.",
        "return list(dict.fromkeys(value))",
        [([], []), ([2, 1, 2, 3, 1], [2, 1, 3]), ([0, -1, 0], [0, -1])],
    ),
    (
        "runs",
        "code",
        "Input: list of integers. Return consecutive runs as [value,count] pairs.",
        "from itertools import groupby\nreturn [[k,len(list(g))] for k,g in groupby(value)]",
        [([], []), ([1, 1, 2, 1], [[1, 2], [2, 1], [1, 1]]), ([0, 0, 0], [[0, 3]])],
    ),
    (
        "rotate",
        "code",
        "Input: {items: integer list, k: nonnegative integer}. Rotate items right by k; empty stays empty.",
        'a=value["items"]; k=value["k"] % len(a) if a else 0\nreturn a[-k:]+a[:-k] if k else list(a)',
        [
            ({"items": [], "k": 8}, []),
            ({"items": [1, 2, 3], "k": 4}, [3, 1, 2]),
            ({"items": [1, 2], "k": 0}, [1, 2]),
        ],
    ),
    (
        "window_sums",
        "code",
        "Input: {items: integer list, k: positive integer}. Return sums of all contiguous windows of exactly k elements.",
        'a=value["items"]; k=value["k"]\nreturn [sum(a[i:i+k]) for i in range(len(a)-k+1)]',
        [
            ({"items": [1, 2, 3, 4], "k": 2}, [3, 5, 7]),
            ({"items": [], "k": 1}, []),
            ({"items": [-2, 3], "k": 3}, []),
        ],
    ),
    (
        "balanced",
        "code",
        "Input: string containing only ()[]{}. Return whether brackets are correctly nested and balanced.",
        'stack=[]\nfor c in value:\n if c in "([{": stack.append(c)\n elif not stack or "([{"[")]}".index(c)] != stack.pop(): return False\nreturn not stack',
        [("", True), ("([]{})", True), ("([)]", False), (")(", False)],
    ),
    (
        "gcd_list",
        "code",
        "Input: integer list. Return nonnegative greatest common divisor of all values; empty returns 0.",
        "from math import gcd\nreturn gcd(*value)",
        [([], 0), ([12, -18, 0], 6), ([7, 11], 1)],
    ),
    (
        "divisors",
        "code",
        "Input: positive integer. Return all positive divisors ascending.",
        "return [n for n in range(1,value+1) if value%n==0]",
        [(1, [1]), (12, [1, 2, 3, 4, 6, 12]), (13, [1, 13])],
    ),
    (
        "flatten",
        "code",
        "Input: nested lists with integer leaves. Return all leaves left-to-right as a flat list.",
        "def walk(x):\n return sum((walk(y) for y in x),[]) if isinstance(x,list) else [x]\nreturn walk(value)",
        [([], []), ([1, [2, [], [3]], 4], [1, 2, 3, 4]), ([[[-1]]], [-1])],
    ),
    (
        "transpose",
        "code",
        "Input: rectangular matrix of integers. Return transpose as lists; [] and rows of length zero return [].",
        "return [list(x) for x in zip(*value)]",
        [([], []), ([[], []], []), ([[1, 2, 3], [4, 5, 6]], [[1, 4], [2, 5], [3, 6]])],
    ),
    (
        "prime_flags",
        "code",
        "Input: integer list. Return bool for primality of each integer (values below 2 are not prime).",
        "return [n>=2 and all(n%d for d in range(2,int(max(n,0)**0.5)+1)) for n in value]",
        [
            ([], []),
            ([-1, 0, 1, 2, 3, 4], [False, False, False, True, True, False]),
            ([49, 97], [False, True]),
        ],
    ),
    (
        "fix_binary_search",
        "bugfix",
        "Repair binary-search boundary behavior: input {items: sorted integer list, target: integer}; return first index of target or -1.",
        'import bisect\na=value["items"]; t=value["target"]; i=bisect.bisect_left(a,t)\nreturn i if i<len(a) and a[i]==t else -1',
        [
            ({"items": [], "target": 1}, -1),
            ({"items": [1, 2, 2, 2, 5], "target": 2}, 1),
            ({"items": [1, 2], "target": 3}, -1),
        ],
    ),
    (
        "fix_chunk_tail",
        "bugfix",
        "Repair dropped-tail chunking: input {items: integer list,k: positive integer}. Return consecutive chunks, retaining the shorter final chunk.",
        'a=value["items"]; k=value["k"]\nreturn [a[i:i+k] for i in range(0,len(a),k)]',
        [
            ({"items": [1, 2, 3, 4, 5], "k": 2}, [[1, 2], [3, 4], [5]]),
            ({"items": [], "k": 3}, []),
            ({"items": [1], "k": 4}, [[1]]),
        ],
    ),
    (
        "fix_negative_max",
        "bugfix",
        "Repair zero-initialized maximum: input nonempty integer list; return maximum including all-negative lists.",
        "return max(value)",
        [([-8, -3, -5], -3), ([0], 0), ([1, 9, 2], 9)],
    ),
    (
        "fix_even_median",
        "bugfix",
        "Repair median: input nonempty integer list. Sort a copy; even sizes return mean of two central values.",
        "a=sorted(value); n=len(a)\nreturn a[n//2] if n%2 else (a[n//2-1]+a[n//2])/2",
        [([9, 1, 3], 3), ([4, 1, 2, 3], 2.5), ([-4, -2], -3)],
    ),
    (
        "fix_empty_prefix",
        "bugfix",
        "Repair common-prefix edge cases: input list of strings; return longest shared prefix, empty list returns empty string.",
        "import os\nreturn os.path.commonprefix(value)",
        [([], ""), (["flower", "flow", "flight"], "fl"), (["abc", ""], "")],
    ),
    (
        "fix_duplicate_pairs",
        "bugfix",
        "Repair pair counting: input integer list; return number of index pairs i<j whose values are equal, including multiplicity.",
        "from collections import Counter\nreturn sum(n*(n-1)//2 for n in Counter(value).values())",
        [([], 0), ([1, 1, 1, 2, 2], 4), ([1, 2, 3], 0)],
    ),
    (
        "fix_leap_year",
        "bugfix",
        "Repair century rule: input Gregorian year integer 1..9999; return bool leap year.",
        "return value%4==0 and (value%100!=0 or value%400==0)",
        [(1900, False), (2000, True), (2024, True), (2023, False)],
    ),
    (
        "fix_overlap",
        "bugfix",
        "Repair half-open interval overlap: input [[a,b],[c,d]], integer endpoints with a<=b,c<=d; empty intervals never overlap. Return bool.",
        "(a,b),(c,d)=value\nreturn max(a,c)<min(b,d)",
        [([[1, 3], [3, 5]], False), ([[1, 5], [2, 4]], True), ([[2, 2], [1, 3]], False)],
    ),
    (
        "fix_percent_decode",
        "bugfix",
        "Repair URL query decoding: input string of ASCII URL-encoded text; decode percent escapes as UTF-8 and plus as space. Malformed percent escapes stay literal.",
        "from urllib.parse import unquote_plus\nreturn unquote_plus(value)",
        [("a+b%2Bc", "a b+c"), ("%C3%A7", "ç"), ("%ZZ", "%ZZ")],
    ),
    (
        "fix_truthy_zero",
        "bugfix",
        "Repair fallback handling: input list of JSON values. Return first value that is not null; false, zero and empty strings count. If all null return null.",
        "return next((x for x in value if x is not None),None)",
        [([None, 0, 5], 0), ([None, False, 1], False), ([None, "", "x"], ""), ([], None)],
    ),
    (
        "group_totals",
        "transform",
        "Input: list of {group:string, amount:integer}. Return dictionary of amount sums by group.",
        'out={}\nfor r in value: out[r["group"]]=out.get(r["group"],0)+r["amount"]\nreturn out',
        [
            ([], {}),
            (
                [
                    {"group": "a", "amount": 3},
                    {"group": "b", "amount": -1},
                    {"group": "a", "amount": 2},
                ],
                {"a": 5, "b": -1},
            ),
        ],
    ),
    (
        "csv_rows",
        "transform",
        "Input: CSV string with header, using comma delimiter and standard double-quote escaping. Return list of dictionaries; empty string returns []. All rows match header width.",
        "import csv,io\nreturn list(csv.DictReader(io.StringIO(value)))",
        [
            ("", []),
            ("a,b\n1,2\n", [{"a": "1", "b": "2"}]),
            ('name,note\nAda,"a,b"\n', [{"name": "Ada", "note": "a,b"}]),
        ],
    ),
    (
        "invert_multimap",
        "transform",
        "Input: dictionary of strings to lists of strings. Invert into value->sorted unique keys; omit empty groups.",
        "out={}\nfor k,vs in value.items():\n for v in vs: out.setdefault(v,set()).add(k)\nreturn {k:sorted(v) for k,v in out.items()}",
        [({}, {}), ({"b": ["x", "x"], "a": ["x", "y"], "c": []}, {"x": ["a", "b"], "y": ["a"]})],
    ),
    (
        "pivot_counts",
        "transform",
        "Input: list of [row,column] string pairs. Return nested dictionary row->column->occurrence count.",
        "out={}\nfor r,c in value:\n d=out.setdefault(r,{}); d[c]=d.get(c,0)+1\nreturn out",
        [
            ([], {}),
            (
                [["a", "x"], ["b", "x"], ["a", "x"], ["a", "y"]],
                {"a": {"x": 2, "y": 1}, "b": {"x": 1}},
            ),
        ],
    ),
    (
        "normalize_words",
        "transform",
        "Input: ASCII string. Lowercase, split on arbitrary whitespace, and join words with single spaces.",
        'return " ".join(value.lower().split())',
        [("", ""), ("  HELLO\tWorld\n", "hello world"), ("A-B  C", "a-b c")],
    ),
    (
        "records_latest",
        "transform",
        "Input: list of {id:string,version:integer,data:JSON}. Return one record per id sorted by id; highest version wins, last input wins ties.",
        'out={}\nfor r in value:\n if r["id"] not in out or r["version"]>=out[r["id"]]["version"]: out[r["id"]]=r\nreturn [out[k] for k in sorted(out)]',
        [
            ([], []),
            (
                [
                    {"id": "a", "version": 2, "data": "x"},
                    {"id": "a", "version": 1, "data": "old"},
                    {"id": "a", "version": 2, "data": "y"},
                ],
                [{"id": "a", "version": 2, "data": "y"}],
            ),
        ],
    ),
    (
        "query_pairs",
        "transform",
        "Input: URL query string. Return list of [key,value] decoded pairs preserving order, duplicates, and blank values; use UTF-8 and plus-to-space.",
        "from urllib.parse import parse_qsl\nreturn [list(p) for p in parse_qsl(value,keep_blank_values=True)]",
        [("", []), ("a=1&a=2&b=", [["a", "1"], ["a", "2"], ["b", ""]]), ("x=a+b", [["x", "a b"]])],
    ),
    (
        "json_lines",
        "transform",
        "Input: string of JSON lines. Ignore whitespace-only lines, parse the others, and return list of parsed values.",
        "import json\nreturn [json.loads(line) for line in value.splitlines() if line.strip()]",
        [("", []), ('1\n\n{"a":2}\nnull\n', [1, {"a": 2}, None]), (" false\n", [False])],
    ),
    (
        "unflatten_keys",
        "transform",
        "Input: dictionary with nonempty dot-separated string keys and JSON values; no path conflicts. Expand into nested dictionaries.",
        'out={}\nfor k,v in value.items():\n d=out; parts=k.split(".")\n for p in parts[:-1]: d=d.setdefault(p,{})\n d[parts[-1]]=v\nreturn out',
        [({}, {}), ({"a.b": 1, "a.c": 2, "d": 3}, {"a": {"b": 1, "c": 2}, "d": 3})],
    ),
    (
        "sort_records",
        "transform",
        "Input: list of {name:string,score:integer}. Return records sorted by descending score then ascending name; exact ties stable.",
        'return sorted(value,key=lambda r:(-r["score"],r["name"]))',
        [
            ([], []),
            (
                [{"name": "b", "score": 2}, {"name": "a", "score": 2}, {"name": "c", "score": 5}],
                [{"name": "c", "score": 5}, {"name": "a", "score": 2}, {"name": "b", "score": 2}],
            ),
        ],
    ),
    (
        "left_join",
        "integration",
        "Input: {left:list of records with id,right:list of records with unique id}. Return [leftRecord,rightRecordOrNull] for each left record in its order.",
        'right={r["id"]:r for r in value["right"]}\nreturn [[r,right.get(r["id"])] for r in value["left"]]',
        [
            ({"left": [], "right": []}, []),
            (
                {"left": [{"id": 2}, {"id": 1}], "right": [{"id": 1, "v": "x"}]},
                [[{"id": 2}, None], [{"id": 1}, {"id": 1, "v": "x"}]],
            ),
        ],
    ),
    (
        "pagination",
        "integration",
        "Input: list of pages; each page is list of {id:string} records. Concatenate, deduplicate by id keeping first occurrence in page order.",
        'seen=set(); out=[]\nfor page in value:\n for r in page:\n  if r["id"] not in seen: out.append(r); seen.add(r["id"])\nreturn out',
        [([], []), ([[{"id": "a"}], [], [{"id": "a"}, {"id": "b"}]], [{"id": "a"}, {"id": "b"}])],
    ),
    (
        "retry_delays",
        "integration",
        "Input: {base:positive integer, cap:positive integer, attempts:nonnegative integer}. Return capped exponential retry delays min(cap,base*2**i) for i=0..attempts-1.",
        'return [min(value["cap"],value["base"]*2**i) for i in range(value["attempts"])]',
        [
            ({"base": 2, "cap": 5, "attempts": 5}, [2, 4, 5, 5, 5]),
            ({"base": 9, "cap": 3, "attempts": 1}, [3]),
            ({"base": 1, "cap": 5, "attempts": 0}, []),
        ],
    ),
    (
        "idempotent_events",
        "integration",
        "Input: list of {id:string,delta:integer}. Return total delta counting only the first event for each id.",
        'seen=set(); total=0\nfor r in value:\n if r["id"] not in seen: total+=r["delta"]; seen.add(r["id"])\nreturn total',
        [
            ([], 0),
            ([{"id": "a", "delta": 3}, {"id": "a", "delta": 9}, {"id": "b", "delta": -1}], 2),
        ],
    ),
    (
        "http_retry",
        "integration",
        "Input: list of HTTP status integers. Return bool list: retry only 408,429 and 500..599 inclusive.",
        "return [s in (408,429) or 500<=s<=599 for s in value]",
        [
            ([], []),
            (
                [200, 400, 408, 429, 499, 500, 599, 600],
                [False, False, True, True, False, True, True, False],
            ),
        ],
    ),
    (
        "headers",
        "integration",
        "Input: list of [ASCII header name, string value]. Return dict with lowercase names, trimming spaces/tabs from values; duplicate names joined with comma followed by space in input order.",
        'out={}\nfor k,v in value:\n k=k.lower(); v=v.strip(" \\t"); out[k]=out[k]+", "+v if k in out else v\nreturn out',
        [([], {}), ([["X-A", " 1 "], ["x-a", "\t2"], ["B", "z"]], {"x-a": "1, 2", "b": "z"})],
    ),
    (
        "path_params",
        "integration",
        "Input: {template:string,path:string} slash-separated paths without query. A template segment {name} matches one nonempty segment. Return parameter dict or null on mismatch; literal segments exact, preserve trailing slash.",
        'a=value["template"].split("/"); b=value["path"].split("/"); out={}\nif len(a)!=len(b): return None\nfor x,y in zip(a,b):\n if x.startswith("{") and x.endswith("}"):\n  if not y: return None\n  out[x[1:-1]]=y\n elif x!=y: return None\nreturn out',
        [
            ({"template": "/u/{id}", "path": "/u/42"}, {"id": "42"}),
            ({"template": "/u/{id}", "path": "/u/"}, None),
            ({"template": "/a", "path": "/a/"}, None),
        ],
    ),
    (
        "config_overlay",
        "integration",
        "Input: list of dictionaries. Merge left to right: later values replace earlier values wholesale, including nested objects and null. Return dictionary.",
        "out={}\nfor d in value: out.update(d)\nreturn out",
        [
            ([], {}),
            ([{"a": {"x": 1}, "b": 2}, {"a": {"y": 3}, "b": None}], {"a": {"y": 3}, "b": None}),
        ],
    ),
    (
        "dependency_order",
        "integration",
        "Input: dictionary node->list of dependency nodes; all nodes present. Return lexicographically smallest valid topological order (smallest currently ready node each step), or null if cyclic.",
        "done=[]\nwhile len(done)<len(value):\n ready=sorted(k for k,v in value.items() if k not in done and all(x in done for x in v))\n if not ready: return None\n done.append(ready[0])\nreturn done",
        [
            ({}, []),
            ({"c": ["a"], "b": [], "a": []}, ["a", "b", "c"]),
            ({"a": ["b"], "b": ["a"]}, None),
        ],
    ),
    (
        "balance_events",
        "integration",
        "Input: {initial:integer,events:list of signed integers}. Apply in order; reject each event that would make balance negative. Return {balance:integer,rejected:list of zero-based event indices}. Initial is nonnegative.",
        'b=value["initial"]; rejected=[]\nfor i,d in enumerate(value["events"]):\n if b+d<0: rejected.append(i)\n else: b+=d\nreturn {"balance":b,"rejected":rejected}',
        [
            ({"initial": 0, "events": []}, {"balance": 0, "rejected": []}),
            ({"initial": 3, "events": [-4, 2, -5, 1]}, {"balance": 1, "rejected": [0]}),
        ],
    ),
    (
        "evidence_votes",
        "analysis",
        "Input: list of {source:string,claim:string}. For each claim return count of distinct sources, duplicates ignored.",
        'out={}\nfor r in value: out.setdefault(r["claim"],set()).add(r["source"])\nreturn {k:len(v) for k,v in out.items()}',
        [
            ([], {}),
            (
                [
                    {"source": "a", "claim": "x"},
                    {"source": "a", "claim": "x"},
                    {"source": "b", "claim": "x"},
                ],
                {"x": 2},
            ),
        ],
    ),
    (
        "contradictions",
        "analysis",
        "Input: list of {key:string,value:string}. Return sorted keys associated with more than one distinct value.",
        'out={}\nfor r in value: out.setdefault(r["key"],set()).add(r["value"])\nreturn sorted(k for k,v in out.items() if len(v)>1)',
        [
            ([], []),
            (
                [
                    {"key": "a", "value": "x"},
                    {"key": "a", "value": "y"},
                    {"key": "b", "value": "z"},
                ],
                ["a"],
            ),
        ],
    ),
    (
        "weighted_score",
        "analysis",
        "Input: list of {score:integer,weight:nonnegative integer}. Return weighted mean, or null if total weight zero.",
        'w=sum(r["weight"] for r in value)\nreturn sum(r["score"]*r["weight"] for r in value)/w if w else None',
        [
            ([], None),
            ([{"score": 10, "weight": 1}, {"score": 4, "weight": 2}], 6),
            ([{"score": 9, "weight": 0}], None),
        ],
    ),
    (
        "pareto",
        "analysis",
        "Input: list of [cost,quality] integer pairs. Return indices of nondominated points in input order. Dominance means cost<= and quality>= with at least one strict; duplicate points do not dominate each other.",
        "return [i for i,(c,q) in enumerate(value) if not any(c2<=c and q2>=q and (c2<c or q2>q) for c2,q2 in value)]",
        [([], []), ([[2, 5], [3, 4], [1, 3], [2, 5]], [0, 2, 3]), ([[1, 1], [1, 2]], [1])],
    ),
    (
        "coverage_gaps",
        "analysis",
        "Input: {required:list of strings,covered:list of strings}. Return sorted unique required items absent from covered.",
        'return sorted(set(value["required"])-set(value["covered"]))',
        [
            ({"required": [], "covered": []}, []),
            ({"required": ["b", "a", "b", "c"], "covered": ["b", "z"]}, ["a", "c"]),
        ],
    ),
    (
        "confusion_counts",
        "analysis",
        "Input: list of [actualBool,predictedBool]. Return dict tp,tn,fp,fn counts.",
        'out=dict.fromkeys(["tp","tn","fp","fn"],0)\nfor a,p in value: out[("t" if a==p else "f")+("p" if p else "n")]+=1\nreturn out',
        [
            ([], {"tp": 0, "tn": 0, "fp": 0, "fn": 0}),
            (
                [[True, True], [False, False], [False, True], [True, False]],
                {"tp": 1, "tn": 1, "fp": 1, "fn": 1},
            ),
        ],
    ),
    (
        "cost_per_success",
        "analysis",
        "Input: list of {cost:number or null,success:bool}. Return sum of ALL costs divided by successes; null if any cost unknown or no successes.",
        'n=sum(r["success"] for r in value)\nreturn sum(r["cost"] for r in value)/n if n and all(r["cost"] is not None for r in value) else None',
        [
            ([], None),
            ([{"cost": 2, "success": True}, {"cost": 4, "success": False}], 6),
            ([{"cost": None, "success": False}, {"cost": 1, "success": True}], None),
        ],
    ),
    (
        "longest_streak",
        "analysis",
        "Input: list of booleans. Return length of longest consecutive true streak, empty returns 0.",
        "best=run=0\nfor b in value:\n run=run+1 if b else 0; best=max(best,run)\nreturn best",
        [([], 0), ([True, True, False, True], 2), ([False, False], 0), ([True, True, True], 3)],
    ),
    (
        "rank_ties",
        "analysis",
        "Input: integer score list. Return competition ranks descending (highest rank 1; ties share rank and leave gaps), in original order.",
        "return [1+sum(t>s for t in value) for s in value]",
        [([], []), ([10, 20, 20, 5], [3, 1, 1, 4]), ([4, 4], [1, 1])],
    ),
    (
        "interval_coverage",
        "analysis",
        "Input: list of integer [start,end] half-open intervals, start<=end. Return total length of union.",
        "end=None; total=0\nfor a,b in sorted(value):\n total+=max(0,b-max(a,end if end is not None else a)); end=max(b,end if end is not None else b)\nreturn total",
        [([], 0), ([[1, 4], [3, 7], [9, 10]], 7), ([[-3, 0], [-1, 2], [5, 5]], 5)],
    ),
]


# This implementation is intentionally kept separate from the delivered task data.
# Validate the literal oracle cases against the independently inspectable reference.
def build():
    rows = []
    for task_id, category, contract, body, cases in TASKS:
        scope = {}
        exec(
            "def solve(value):\n" + "".join(" " + line + "\n" for line in body.splitlines()), scope
        )
        for value, expected in cases:
            actual = scope["solve"](value)
            assert actual == expected, (task_id, value, actual, expected)
        rows.append(
            {
                "id": task_id,
                "category": category,
                "contract": contract,
                "cases": [{"input": v, "expected": e} for v, e in cases],
            }
        )
    assert len(rows) == 50 and len({r["id"] for r in rows}) == 50
    path = Path(__file__).with_name("core-v1.json")
    path.write_text(
        json.dumps(
            {"schema_version": 1, "suite": "core-v1", "tasks": rows}, ensure_ascii=False, indent=2
        )
        + "\n"
    )


if __name__ == "__main__":
    build()
