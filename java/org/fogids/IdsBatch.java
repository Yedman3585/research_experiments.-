package org.fogids;

import java.nio.file.*;
import java.io.*;
import java.util.*;
import org.cloudbus.cloudsim.*;
import org.cloudbus.cloudsim.core.*;
import org.cloudbus.cloudsim.power.PowerHost;
import org.cloudbus.cloudsim.provisioners.RamProvisionerSimple;
import org.cloudbus.cloudsim.sdn.overbooking.*;
import org.fog.application.Application;
import org.fog.application.AppModule;
import org.fog.entities.*;
import org.fog.policy.AppModuleAllocationPolicy;
import org.fog.scheduler.StreamOperatorScheduler;
import org.fog.utils.*;

/** A finite ready-inference batch; actual FogDevice CPU sharing and uplink queues. */
public final class IdsBatch extends SimEntity {
    static final int EMIT = 90001, FINISH = 90002;
    static final String APP = "ids-batch";
    final List<FogDevice> nodes;
    final List<String[]> tasks;
    final Map<Integer, Double> completed = new HashMap<>();
    final Map<Integer, Integer> executionNodes = new HashMap<>();
    final double release, decisionDelay, horizon;
    final Path output;
    final Application app;

    IdsBatch(List<FogDevice> nodes, List<String[]> tasks, double release,
             double delay, double horizon, Path output) {
        super("ids-driver");
        this.nodes = nodes; this.tasks = tasks; this.release = release;
        this.decisionDelay = delay; this.horizon = horizon; this.output = output;
        app = Application.createApplication(APP, getId());
        for (FogDevice node : nodes) {
            node.setControllerId(getId());
            double mips = node.getHost().getTotalMips();
            app.getModules().add(new AppModule(FogUtils.generateEntityId(), "ids_" + node.getName(),
                APP, getId(), mips, 128, 1000, 1000, "Xen", new InferenceScheduler(mips), new HashMap<>()));
        }
    }

    @Override public void startEntity() {
        for (FogDevice node : nodes) {
            sendNow(node.getId(), FogEvents.APP_SUBMIT, app);
            sendNow(node.getId(), FogEvents.LAUNCH_MODULE, app.getModuleByName("ids_" + node.getName()));
        }
        send(getId(), release + decisionDelay, EMIT);
        send(getId(), horizon, FINISH);
    }

    @Override public void processEvent(SimEvent ev) {
        if (ev.getTag() == EMIT) {
            for (String[] task : tasks) {
                int id = Integer.parseInt(task[0]);
                int m = Integer.parseInt(task[1]);
                Tuple tuple = new Tuple(APP, id, Tuple.UP, Long.parseLong(task[2]), 1,
                    Long.parseLong(task[3]), 1, new UtilizationModelFull(),
                    new UtilizationModelFull(), new UtilizationModelFull());
                tuple.setUserId(getId());
                tuple.setTupleType("IDS_" + id);
                tuple.setSrcModuleName("ready_features");
                tuple.setDestModuleName("ids_" + nodes.get(m).getName());
                tuple.setActualTupleId(id);
                sendNow(nodes.get(0).getId(), FogEvents.TUPLE_ARRIVAL, tuple);
            }
        } else if (ev.getTag() == CloudSimTags.CLOUDLET_RETURN) {
            Tuple tuple = (Tuple) ev.getData();
            completed.put(tuple.getCloudletId(), CloudSim.clock());
            executionNodes.put(tuple.getCloudletId(), ev.getSource());
        } else if (ev.getTag() == FINISH) {
            try (PrintWriter writer = new PrintWriter(Files.newBufferedWriter(output))) {
                writer.println("task_id,node,completed,latency_s,deadline_s,missed");
                for (String[] task : tasks) {
                    int id = Integer.parseInt(task[0]);
                    int m = Integer.parseInt(task[1]);
                    double deadline = Double.parseDouble(task[4]);
                    Double finish = completed.get(id);
                    if (finish != null && executionNodes.get(id) != nodes.get(m).getId())
                        throw new IllegalStateException("Tuple executed on incorrect node");
                    double latency = finish == null ? Double.NaN : finish - release;
                    writer.printf(Locale.ROOT, "%d,%s,%s,%s,%.9f,%s%n", id, nodes.get(m).getName(),
                        finish != null, finish == null ? "" : String.format(Locale.ROOT, "%.9f", latency),
                        deadline, finish == null || latency > deadline + 0.00001);
                }
            } catch (IOException error) { throw new RuntimeException(error); }
            CloudSim.stopSimulation();
        }
    }
    @Override public void shutdownEntity() { }

    // Upstream TupleScheduler inherits an empty getCurrentRequestedMips().
    // PowerHost then revokes CPU on periodic updates. Explicit demand keeps
    // a busy inference VM allocated; time sharing within the VM stays upstream.
    static final class InferenceScheduler extends CloudletSchedulerTimeShared {
        final double mips;
        InferenceScheduler(double mips) { this.mips = mips; }
        @Override public List<Double> getCurrentRequestedMips() {
            return Collections.singletonList(runningCloudlets() > 0 ? mips : 0.0);
        }
    }

    static FogDevice node(String[] row) throws Exception {
        String name = row[0]; long mips = Long.parseLong(row[1]);
        long bandwidth = Long.parseLong(row[2]);
        List<Pe> pes = Collections.singletonList(new Pe(0, new PeProvisionerOverbooking(mips)));
        PowerHost host = new PowerHost(FogUtils.generateEntityId(), new RamProvisionerSimple(4096),
            new BwProvisionerOverbooking(10000000), 1000000, pes,
            new StreamOperatorScheduler(pes), new FogLinearPowerModel(100, 50));
        List<Host> hosts = Collections.singletonList(host);
        FogDeviceCharacteristics characteristics = new FogDeviceCharacteristics("x86", "Linux", "Xen",
            host, 0, 0, 0, 0, 0);
        FogDevice device = new FogDevice(name, characteristics, new AppModuleAllocationPolicy(hosts),
            new LinkedList<Storage>(), 0.01, bandwidth, bandwidth, 0, 0);
        device.setUplinkLatency(Double.parseDouble(row[3]));
        return device;
    }

    static List<String[]> read(Path path) throws IOException {
        List<String[]> rows = new ArrayList<>();
        List<String> lines = Files.readAllLines(path);
        for (String line : lines.subList(1, lines.size()))
            if (!line.trim().isEmpty()) rows.add(line.split(","));
        return rows;
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 6) throw new IllegalArgumentException("nodes.csv tasks.csv output.csv release delay horizon");
        CloudSim.init(1, Calendar.getInstance(), false, 0.000001);
        Log.disable();
        Logger.ENABLED = true;
        List<FogDevice> nodes = new ArrayList<>();
        for (String[] row : read(Paths.get(args[0]))) nodes.add(node(row));
        for (int i = 0; i < nodes.size(); i++) {
            FogDevice child = nodes.get(i);
            child.setLevel(nodes.size() - 1 - i);
            child.setParentId(i + 1 < nodes.size() ? nodes.get(i+1).getId() : -1);
            if (i+1 < nodes.size()) {
                FogDevice parent = nodes.get(i+1);
                parent.getChildrenIds().add(child.getId());
                parent.getChildToLatencyMap().put(child.getId(), child.getUplinkLatency());
            }
        }
        new IdsBatch(nodes, read(Paths.get(args[1])), Double.parseDouble(args[3]),
            Double.parseDouble(args[4]), Double.parseDouble(args[5]), Paths.get(args[2]));
        CloudSim.startSimulation();
        CloudSim.stopSimulation();
    }
}
