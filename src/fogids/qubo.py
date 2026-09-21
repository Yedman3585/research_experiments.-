"""Small, dependency-free placement QUBO. Upper-triangular coefficient convention."""
from dataclasses import dataclass, field
import itertools
import math
import random


@dataclass
class Qubo:
    labels: list = field(default_factory=list)
    terms: dict = field(default_factory=dict)
    offset: float = 0.0

    def variable(self, label):
        self.labels.append(label)
        return len(self.labels) - 1

    def add(self, i, j, value):
        key = min(i, j), max(i, j)
        self.terms[key] = self.terms.get(key, 0.0) + value

    def square(self, coefficients, target, penalty):
        self.offset += penalty * target * target
        for i, a in coefficients.items():
            self.add(i, i, penalty * (a * a - 2 * target * a))
        for (i, a), (j, b) in itertools.combinations(coefficients.items(), 2):
            self.add(i, j, 2 * penalty * a * b)

    def energy(self, bits):
        return self.offset + sum(v * bits[i] * bits[j] for (i, j), v in self.terms.items())


def validate(c):
    if [n['name'] for n in c['nodes']] != ['edge', 'fog', 'cloud']:
        raise ValueError('This prototype requires the edge -> fog -> cloud topology')
    if not 1 <= len(c['tasks']) <= 8:
        raise ValueError('Tiny exact-oracle demo supports 1..8 ready tasks')
    if len({t['id'] for t in c['tasks']}) != len(c['tasks']):
        raise ValueError('Task ids must be unique')
    for t in c['tasks']:
        if not isinstance(t['id'], int) or t['id'] < 0:
            raise ValueError('Task ids must be nonnegative integers')
        if not isinstance(t['demand_units'], int) or t['demand_units'] <= 0:
            raise ValueError('Compute demands must be positive integer units')
        if not isinstance(t['input_bytes'], int):
            raise ValueError('Input sizes must be integer bytes')
        if min(t['input_bytes'], t['deadline_s'], t['priority']) <= 0:
            raise ValueError('Task sizes, deadlines and priorities must be positive')
    for n in c['nodes']:
        if not isinstance(n['capacity_units'], int) or n['capacity_units'] < 0:
            raise ValueError('Capacity must be a nonnegative integer')
        if n['mips'] <= 0 or n['uplink_bytes_s'] <= 0 or n['uplink_latency_s'] < 0:
            raise ValueError('Invalid node rates')
        if n['capacity_units'] * c['capacity_unit_mi'] > n['mips'] * c['capacity_horizon_s'] + 1e-9:
            raise ValueError('Admission capacity exceeds the configured compute horizon')
    if not all(isinstance(c[k], int) for k in ['capacity_unit_mi', 'seed', 'sa_reads', 'sa_sweeps']):
        raise ValueError('Integer MI unit, seed and solver budgets required')
    if min(c['capacity_unit_mi'], c['capacity_horizon_s'], c['sa_reads'], c['sa_sweeps']) <= 0:
        raise ValueError('Positive units, horizon and solver budget required')
    if min(c['deadline_weight'], c['contention_weight'], c['release_s']) < 0:
        raise ValueError('Negative costs or release time not supported')
    if c['simulation_horizon_s'] <= c['release_s']:
        raise ValueError('Simulation must extend beyond release')


def costs(c):
    tasks, nodes = c['tasks'], c['nodes']
    linear, pair = {}, {}
    for i, t in enumerate(tasks):
        for m, node in enumerate(nodes):
            network = sum(n['uplink_latency_s'] + t['input_bytes'] / n['uplink_bytes_s'] for n in nodes[:m])
            latency = network + t['demand_units'] * c['capacity_unit_mi'] / node['mips']
            linear[i, m] = t['priority'] * (latency + c['deadline_weight'] * max(0, latency - t['deadline_s']))
    for i, j in itertools.combinations(range(len(tasks)), 2):
        for m, node in enumerate(nodes):
            pair[i, j, m] = c['contention_weight'] * (tasks[i]['priority'] + tasks[j]['priority']) * min(tasks[i]['demand_units'], tasks[j]['demand_units']) * c['capacity_unit_mi'] / node['mips']
    return linear, pair


def loads(c, assignment):
    return [sum(t['demand_units'] for t, a in zip(c['tasks'], assignment) if a == m) for m in range(len(c['nodes']))]


def feasible(c, assignment):
    return (len(assignment) == len(c['tasks']) and all(a in range(len(c['nodes'])) for a in assignment)
            and all(v <= n['capacity_units'] for v, n in zip(loads(c, assignment), c['nodes'])))


def objective(assignment, linear, pair):
    return sum(linear[i, m] for i, m in enumerate(assignment)) + sum(v for (i, j, m), v in pair.items() if assignment[i] == assignment[j] == m)


def greedy(c, linear, pair):
    """Largest-demand-first, incremental-cost placement; explicit failure if stranded."""
    a = [-1] * len(c['tasks'])
    remaining = [n['capacity_units'] for n in c['nodes']]
    order = sorted(range(len(a)), key=lambda i: (-c['tasks'][i]['demand_units'], -c['tasks'][i]['priority'], i))
    for i in order:
        eligible = [m for m in range(len(remaining)) if remaining[m] >= c['tasks'][i]['demand_units']]
        if not eligible:
            raise ValueError('Greedy could not construct a feasible incumbent; change this tiny scenario')
        def marginal(m):
            return linear[i, m] + sum(pair[min(i,j), max(i,j), m] for j in range(len(a)) if a[j] == m)
        a[i] = min(eligible, key=marginal)
        remaining[a[i]] -= c['tasks'][i]['demand_units']
    return a


def slack_weights(capacity):
    weights, covered = [], 0
    while covered < capacity:
        w = min(covered + 1, capacity - covered)
        weights.append(w)
        covered += w
    return weights


def build(c, incumbent):
    linear, pair = costs(c)
    q = Qubo()
    y = {(i, m): q.variable(f'y_{i}_{m}') for i in range(len(c['tasks'])) for m in range(len(c['nodes']))}
    for key, v in linear.items():
        q.add(y[key], y[key], v)
    for (i, j, m), v in pair.items():
        q.add(y[i, m], y[j, m], v)
    # Nonnegative objective, integer residuals: every infeasible bitstring has
    # energy >= P > the feasible incumbent U. This bound is specific to this model.
    penalty = objective(incumbent, linear, pair) + 1.0
    for i in range(len(c['tasks'])):
        q.square({y[i, m]: 1 for m in range(len(c['nodes']))}, 1, penalty)
    slack = []
    for m, node in enumerate(c['nodes']):
        s = {q.variable(f's_{m}_{k}'): w for k, w in enumerate(slack_weights(node['capacity_units']))}
        slack.append(s)
        q.square({**{y[i, m]: t['demand_units'] for i, t in enumerate(c['tasks'])}, **s}, node['capacity_units'], penalty)
    return q, y, slack, penalty


def encode(c, assignment, q, y, slack):
    bits = [0] * len(q.labels)
    for i, m in enumerate(assignment):
        bits[y[i, m]] = 1
    for m, s in enumerate(slack):
        residual = c['nodes'][m]['capacity_units'] - loads(c, assignment)[m]
        for values in itertools.product((0, 1), repeat=len(s)):
            if sum(v * w for v, w in zip(values, s.values())) == residual:
                for k, v in zip(s, values):
                    bits[k] = v
                break
        else:
            raise ValueError('Cannot encode infeasible assignment')
    return bits


def decode(c, bits, y):
    assignment = []
    for i in range(len(c['tasks'])):
        chosen = [m for m in range(len(c['nodes'])) if bits[y[i, m]]]
        if len(chosen) != 1:
            return None
        assignment.append(chosen[0])
    return assignment if feasible(c, assignment) else None


def anneal(q, initial, seed, reads, sweeps):
    """Classical single-bit Metropolis SA; not SQA and not a QPU call."""
    rng = random.Random(seed)
    neighbours = [[] for _ in q.labels]
    diagonal = [0.0] * len(q.labels)
    for (i, j), v in q.terms.items():
        if i == j:
            diagonal[i] += v
        else:
            neighbours[i].append((j, v))
            neighbours[j].append((i, v))
    scale = max(1.0, max(abs(v) for v in diagonal))
    samples = []
    for read in range(reads):
        x = initial.copy() if read == 0 else [rng.randrange(2) for _ in q.labels]
        best, best_energy = x.copy(), q.energy(x)
        order = list(range(len(x)))
        for sweep in range(sweeps):
            temperature = scale * (0.001 / scale) ** (sweep / max(1, sweeps - 1))
            rng.shuffle(order)
            for i in order:
                delta = (1 - 2*x[i]) * (diagonal[i] + sum(v*x[j] for j, v in neighbours[i]))
                if delta <= 0 or rng.random() < math.exp(-delta / temperature):
                    x[i] ^= 1
            energy = q.energy(x)
            if energy < best_energy:
                best, best_energy = x.copy(), energy
        samples.append((best_energy, best))
    return sorted(samples, key=lambda p: p[0])


def exact(c, linear, pair):
    candidates = (a for a in itertools.product(range(len(c['nodes'])), repeat=len(c['tasks'])) if feasible(c, a))
    return list(min(candidates, key=lambda a: objective(a, linear, pair)))
