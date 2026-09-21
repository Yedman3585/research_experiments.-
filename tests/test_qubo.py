import itertools
import json
from pathlib import Path
import unittest
from fogids import qubo

ROOT = Path(__file__).resolve().parents[1]


class QuboTests(unittest.TestCase):
    def setUp(self):
        self.c = json.loads((ROOT / 'configs/ids-small.json').read_text())

    def test_expansion_matches_constraints_for_every_bitstring(self):
        c = self.c
        c['tasks'] = c['tasks'][:2]
        c['tasks'][1]['demand_units'] = 1
        c['nodes'] = c['nodes'][:2]
        for n in c['nodes']:
            n['capacity_units'] = 1
        incumbent = [0, 1]
        q, y, slack, p = qubo.build(c, incumbent)
        linear, pair = qubo.costs(c)
        best_feasible = min(qubo.objective(a, linear, pair) for a in [(0,1), (1,0)])
        minimum = float('inf')
        for bits in itertools.product((0,1), repeat=len(q.labels)):
            raw = sum(v*bits[y[key]] for key,v in linear.items())
            raw += sum(v*bits[y[i,m]]*bits[y[j,m]] for (i,j,m),v in pair.items())
            residual = sum((sum(bits[y[i,m]] for m in range(2))-1)**2 for i in range(2))
            residual += sum((sum(bits[y[i,m]] for i in range(2)) + sum(bits[k]*v for k,v in slack[m].items()) - 1)**2 for m in range(2))
            self.assertAlmostEqual(q.energy(bits), raw + p*residual)
            if residual:
                self.assertGreater(q.energy(bits), best_feasible)
            minimum = min(minimum, q.energy(bits))
        self.assertAlmostEqual(minimum, best_feasible)

    def test_all_feasible_assignments_have_identical_qubo_and_original_cost(self):
        c = self.c
        linear, pair = qubo.costs(c)
        incumbent = qubo.greedy(c, linear, pair)
        q, y, slack, _ = qubo.build(c, incumbent)
        for a in itertools.product(range(3), repeat=len(c['tasks'])):
            if qubo.feasible(c, a):
                bits = qubo.encode(c, a, q, y, slack)
                self.assertAlmostEqual(q.energy(bits), qubo.objective(a, linear, pair))
                self.assertEqual(qubo.decode(c, bits, y), list(a))

    def test_bounded_slack_covers_every_integer_and_never_exceeds_capacity(self):
        for capacity in range(25):
            weights = qubo.slack_weights(capacity)
            values = {sum(v*w for v,w in zip(bits, weights)) for bits in itertools.product((0,1), repeat=len(weights))}
            self.assertEqual(values, set(range(capacity+1)))

    def test_sa_reproducible_and_carries_feasible_incumbent(self):
        linear, pair = qubo.costs(self.c)
        a = qubo.greedy(self.c, linear, pair)
        q,y,s,_ = qubo.build(self.c, a)
        initial = qubo.encode(self.c, a, q,y,s)
        first = qubo.anneal(q,initial,7,4,30)
        self.assertEqual(first, qubo.anneal(q,initial,7,4,30))
        self.assertLessEqual(first[0][0], q.energy(initial) + 1e-8)
        self.assertIsNotNone(qubo.decode(self.c, first[0][1], y))

    def test_reject_invalid_units_and_capacity(self):
        qubo.validate(self.c)
        self.c['nodes'][0]['capacity_units'] = 100
        with self.assertRaises(ValueError):
            qubo.validate(self.c)


if __name__ == '__main__':
    unittest.main()
