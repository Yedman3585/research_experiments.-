"""Physical checks against analytic single-task and CPU-sharing cases."""
import csv
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ifogsim', ROOT / 'scripts/ifogsim.py')
java = importlib.util.module_from_spec(spec)
spec.loader.exec_module(java)


class SimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (java.CLASSES / 'org/fog/entities/FogDevice.class').exists():
            raise RuntimeError('Run fogids build before integration tests')
        subprocess.run(['javac','-cp',java.classpath(),'-d',str(java.CLASSES),str(ROOT / 'java/org/fogids/IdsBatch.java')], check=True)

    def simulate(self, target, count=1, delay=0, horizon=8):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            (p/'nodes.csv').write_text('name,mips,bw,latency\nedge,1000,2000000,0.02\nfog,2000,1000000,0.08\ncloud,4000,1000000,0\n')
            (p/'tasks.csv').write_text('id,node,mi,bytes,deadline\n' + ''.join(f'{i},{target},1000,100000,5\n' for i in range(count)))
            result = subprocess.run(['java','-cp',java.classpath(),'org.fogids.IdsBatch',
                str(p/'nodes.csv'),str(p/'tasks.csv'),str(p/'out.csv'),'1',str(delay),str(horizon)],
                capture_output=True,text=True,check=True,timeout=20)
            self.assertNotIn('Exception',result.stdout + result.stderr)
            with (p/'out.csv').open() as f:
                return list(csv.DictReader(f))

    def test_local_compute_seconds(self):
        r = self.simulate(0)[0]
        self.assertEqual(r['completed'],'true')
        self.assertAlmostEqual(float(r['latency_s']),1,delta=0.011)

    def test_cloud_network_serialization_plus_compute(self):
        r = self.simulate(2)[0]
        # Two uplinks: .05+.02+.1+.08; cloud compute .25 seconds.
        self.assertAlmostEqual(float(r['latency_s']),0.5,delta=0.011)

    def test_shared_cpu_not_independent_full_speed_tasks(self):
        rows = self.simulate(0,count=2)
        self.assertEqual(len(rows),2)
        for r in rows:
            self.assertAlmostEqual(float(r['latency_s']),2,delta=0.011)

    def test_decision_delay_is_in_simulation_latency(self):
        r = self.simulate(0,delay=0.25)[0]
        self.assertAlmostEqual(float(r['latency_s']),1.25,delta=0.011)

    def test_censored_tasks_count_as_misses(self):
        r = self.simulate(0,horizon=1.5)[0]
        self.assertEqual(r['completed'],'false')
        self.assertEqual(r['missed'],'true')
        self.assertEqual(r['latency_s'],'')


if __name__ == '__main__':
    unittest.main()
