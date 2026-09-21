"""Reproducible tiny placement experiment, not an online scheduling service."""
import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import time
from . import qubo

ROOT = Path(__file__).resolve().parents[2]


def write_csv(path, header, rows):
    with path.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def run(config_path, output):
    c = json.loads(Path(config_path).read_text())
    qubo.validate(c)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / 'config.json').write_text(json.dumps(c, indent=2) + '\n')
    t0 = time.perf_counter()
    linear, pair = qubo.costs(c)
    incumbent = qubo.greedy(c, linear, pair)
    greedy_seconds = time.perf_counter() - t0
    t0 = time.perf_counter()
    q, y, slack, penalty = qubo.build(c, incumbent)
    initial = qubo.encode(c, incumbent, q, y, slack)
    build_seconds = time.perf_counter() - t0
    t0 = time.perf_counter()
    samples = qubo.anneal(q, initial, c['seed'], c['sa_reads'], c['sa_sweeps'])
    solve_seconds = time.perf_counter() - t0
    t0 = time.perf_counter()
    valid = [a for _, bits in samples if (a := qubo.decode(c, bits, y)) is not None]
    candidates = [incumbent, *valid]
    chosen = min(candidates, key=lambda a: qubo.objective(a, linear, pair))
    decode_seconds = time.perf_counter() - t0
    oracle = qubo.exact(c, linear, pair)
    sa_seconds = greedy_seconds + build_seconds + solve_seconds + decode_seconds
    spec = importlib.util.spec_from_file_location('ifogsim_build', ROOT / 'scripts/ifogsim.py')
    java = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(java)
    if not (java.CLASSES / 'org/fog/entities/FogDevice.class').exists():
        java.build()
    subprocess.run(['javac', '-encoding', 'UTF-8', '-cp', java.classpath(), '-d', str(java.CLASSES),
                    str(ROOT / 'java/org/fogids/IdsBatch.java')], check=True)
    nodes_path = output / 'nodes.csv'
    write_csv(nodes_path, ['name', 'mips', 'uplink_bytes_s', 'uplink_latency_s'],
              [(n['name'], n['mips'], n['uplink_bytes_s'], n['uplink_latency_s']) for n in c['nodes']])
    report = {'seed': c['seed'], 'variables': len(q.labels), 'qubo_terms': len(q.terms),
              'penalty': penalty, 'build_s': build_seconds, 'sa_s': solve_seconds,
              'decode_s': decode_seconds, 'sa_feasible_read_count': len(valid),
              'sa_reads': c['sa_reads'], 'deadline_tolerance_s': 0.00001,
              'incumbent_retained': chosen == incumbent, 'oracle_surrogate': qubo.objective(oracle, linear, pair),
              'oracle_assignment': oracle, 'runs': {}}
    (output / 'qubo.json').write_text(json.dumps({'labels': q.labels, 'offset': q.offset,
        'terms': [[i,j,v] for (i,j),v in q.terms.items()]}, indent=2) + '\n')
    # Identical workload in fresh JVMs. Separate the placement-only effect from
    # the measured decision delay; Java startup/compilation are harness overhead.
    for name, assignment, delay in [('greedy', incumbent, 0), ('qubo_sa', chosen, 0),
                                   ('greedy_with_delay', incumbent, greedy_seconds),
                                   ('qubo_sa_with_delay', chosen, sa_seconds)]:
        if c['release_s'] + delay >= c['simulation_horizon_s']:
            raise ValueError('Decision delay exceeds simulation horizon; increase horizon')
        tasks_path, result_path = output / f'{name}-tasks.csv', output / f'{name}-results.csv'
        write_csv(tasks_path, ['id', 'node_index', 'compute_mi', 'input_bytes', 'deadline_s'],
                  [(t['id'], m, t['demand_units']*c['capacity_unit_mi'], t['input_bytes'], t['deadline_s'])
                   for t,m in zip(c['tasks'], assignment)])
        wall_start = time.perf_counter()
        with (output / f'{name}.log').open('w') as log:
            subprocess.run(['java', '-Xmx1g', '-cp', java.classpath(), 'org.fogids.IdsBatch',
                str(nodes_path), str(tasks_path), str(result_path), str(c['release_s']), str(delay),
                str(c['simulation_horizon_s'])], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
        java_wall = time.perf_counter() - wall_start
        with result_path.open() as f:
            rows = list(csv.DictReader(f))
        if len(rows) != len(c['tasks']) or {int(r['task_id']) for r in rows} != {t['id'] for t in c['tasks']}:
            raise RuntimeError('Simulator output missing tasks')
        latency = [float(r['latency_s']) for r in rows if r['completed'] == 'true']
        report['runs'][name] = {'assignment': assignment, 'capacity_load_units': qubo.loads(c, assignment),
            'surrogate': qubo.objective(assignment, linear, pair), 'applied_decision_delay_s': delay,
            'java_process_wall_s': java_wall, 'completed': len(latency),
            'deadline_misses': sum(r['missed'] == 'true' for r in rows),
            'mean_latency_completed_s': sum(latency)/len(latency) if latency else None,
            'max_latency_completed_s': max(latency) if latency else None}
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    print(f'Artifacts: {output}')
    return report
