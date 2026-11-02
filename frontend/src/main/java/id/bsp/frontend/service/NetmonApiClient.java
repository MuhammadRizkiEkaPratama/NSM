package id.bsp.frontend.service;

import id.bsp.frontend.dto.DeviceDto;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.List;

@Service
public class NetmonApiClient {

    /**
     * Header telling Python which tenant is being served. Taken from {@link KonteksTenant}, which
     * {@code TenantFilter} fills from the logged-in account, never from the client. Without it
     * Python applies no filter (platform admins).
     */
    static final String KEPALA_TENANT = "X-NSM-Tenant";

    private final RestClient client = RestClient.builder()
            .baseUrl("http://localhost:8000")
            .requestInitializer(req -> {
                Long t = KonteksTenant.sekarang();
                if (t != null) {
                    req.getHeaders().add(KEPALA_TENANT, String.valueOf(t));
                }
            })
            .build();

    public List<DeviceDto> getDevices() {
        return client.get()
                .uri("/devices")
                .retrieve()
                .body(new org.springframework.core.ParameterizedTypeReference<List<DeviceDto>>() {});
    }

    public Object getDeviceInfo(int id) {
        return client.get()
                .uri("/devices/" + id + "/info")
                .retrieve()
                .body(Object.class);
    }

    // Report: Java only forwards JSON from Python and computes nothing, hence the `Object` return type instead of DTOs.

    public Object getReportSummary(String period) {
        return client.get()
                .uri("/report/summary?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    public Object getReportSparkline(String period) {
        return client.get()
                .uri("/report/sparkline?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    public Object getReportAvailability(String period) {
        return client.get()
                .uri("/report/availability?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    /**
     * SLO and error budget per device. The window is fixed at 30 days and ignores the page's period
     * selector: an error budget only means something over a range long enough to contain several outages.
     */
    public Object getReportSlo() {
        return client.get()
                .uri("/report/slo?period=30d")
                .retrieve()
                .body(Object.class);
    }

    public Object getDeviceHistory(int id, String period) {
        return client.get()
                .uri("/devices/" + id + "/history?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    public Object getDeviceBandwidth(int id, String period) {
        return client.get()
                .uri("/devices/" + id + "/bandwidth?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    /** Pause / resume monitoring. The only call that WRITES. */
    public Object setDeviceAktif(int id, boolean aktif, String alasan, String oleh) {
        // HashMap, not Map.of: the latter rejects null values, and the reason may legitimately be empty.
        java.util.Map<String, Object> badan = new java.util.HashMap<>();
        badan.put("aktif", aktif);
        badan.put("alasan", alasan);
        badan.put("oleh", oleh);
        return client.post()
                .uri("/devices/" + id + "/aktif")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(badan)
                .retrieve()
                .body(Object.class);
    }

    /** Turns email notifications on or off for a device. Also writes. */
    public Object setDevicePenting(int id, boolean penting) {
        return client.post()
                .uri("/devices/" + id + "/penting")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(java.util.Map.of("penting", penting))
                .retrieve()
                .body(Object.class);
    }

    // Downloads an Excel file (raw bytes, not JSON). `oleh` is passed so the author name is printed in the report.

    public org.springframework.http.ResponseEntity<byte[]> exportReport(
            String period, String oleh) {
        return client.get()
                .uri("/report/export?period=" + period + "&oleh=" + enc(oleh))
                .retrieve()
                .toEntity(byte[].class);
    }

    public org.springframework.http.ResponseEntity<byte[]> exportRiwayat(
            int id, String period, String oleh) {
        return client.get()
                .uri("/devices/" + id + "/export?period=" + period + "&oleh=" + enc(oleh))
                .retrieve()
                .toEntity(byte[].class);
    }

    public org.springframework.http.ResponseEntity<byte[]> exportReportWord(
            String period, String oleh) {
        return client.get()
                .uri("/report/export-word?period=" + period + "&oleh=" + enc(oleh))
                .retrieve()
                .toEntity(byte[].class);
    }

    private String enc(String s) {
        return java.net.URLEncoder.encode(s == null ? "" : s,
                java.nio.charset.StandardCharsets.UTF_8);
    }

    public Object getDeviceChart(int id, int points) {
        return client.get()
                .uri("/devices/" + id + "/chart?points=" + points)
                .retrieve()
                .body(Object.class);
    }

    public Object getDeviceLatest(int id) {
        return client.get()
                .uri("/devices/" + id + "/latest")
                .retrieve()
                .body(Object.class);
    }

    /**
     * Latest traffic rate of ALL devices in one call. The dashboard refreshes every 5 seconds, so
     * one call per device would mean dozens of requests per minute through Java, Python and SQLite.
     */
    /**
     * Diagnosis: what broke, who is affected, first step. All cause/effect reasoning and wording is
     * built in Python so the page and the report never disagree.
     */
    public Object getDiagnosis() {
        return client.get()
                .uri("/diagnosis")
                .retrieve()
                .body(Object.class);
    }

    public Object getBandwidthTerkini() {
        return client.get()
                .uri("/devices/bandwidth-terkini")
                .retrieve()
                .body(Object.class);
    }

    public Object getDeviceEvents(int id, String period) {
        return client.get()
                .uri("/devices/" + id + "/events?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    // Services and backup: Java only forwards JSON; health decisions are computed by Python.

    public Object getServices(String period) {
        return client.get()
                .uri("/services?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    /**
     * Current service state, grouped by device, for the dashboard cards. No period parameter: a
     * period calculation is too expensive for a five-second refresh.
     */
    public Object getServicesRingkas() {
        return client.get()
                .uri("/services/ringkas")
                .retrieve()
                .body(Object.class);
    }

    public Object getDeviceServices(int id, String period) {
        return client.get()
                .uri("/devices/" + id + "/services?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    public Object getServiceHistory(int id, String period) {
        return client.get()
                .uri("/services/" + id + "/history?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    public Object getInsidenTerakhir() {
        return client.get()
                .uri("/report/insiden-terakhir")
                .retrieve()
                .body(Object.class);
    }

    public Object getBackupStatus() {
        return client.get()
                .uri("/backup/status")
                .retrieve()
                .body(Object.class);
    }

    public Object getBackupIsi(String nama) {
        return client.get()
                .uri(uriBuilder -> uriBuilder.path("/backup/isi")
                        .queryParam("nama", nama).build())
                .retrieve()
                .body(Object.class);
    }

    public Object getDeviceTraffic(int id, String period) {
        return client.get()
                .uri("/devices/" + id + "/traffic?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    /**
     * Firewall rules of each Linux device. Read-only at all three layers on purpose: Java forwards,
     * Python only runs `ufw status`, and the server's sudo rules allow only those commands.
     */
    public Object getFirewall() {
        return client.get()
                .uri("/firewall")
                .retrieve()
                .body(Object.class);
    }

    /**
     * Blocks one IP on a device firewall (auto-ban). WRITES. Java does not judge whether it is
     * allowed; the allowlist guard lives in Python (`penjaga_aksi.blokir`).
     */
    public Object postFirewallBlokir(java.util.Map<String, Object> badan) {
        return client.post()
                .uri("/firewall/blokir")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(badan)
                .retrieve()
                .body(Object.class);
    }

    public Object postFirewallBukaBlokir(java.util.Map<String, Object> badan) {
        return client.post()
                .uri("/firewall/buka-blokir")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(badan)
                .retrieve()
                .body(Object.class);
    }

    /**
     * Blocks one IP in a router ACL (second layer for Location B), separate from `postFirewallBlokir`
     * (ufw). The guard is `penjaga_aksi.block_acl` in Python.
     */
    public Object postFirewallBlokirAcl(java.util.Map<String, Object> badan) {
        return client.post()
                .uri("/firewall/blokir-acl")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(badan)
                .retrieve()
                .body(Object.class);
    }

    /**
     * Dashboard topology map as RAW JSON in a String, not `Object`. Deliberately not parsed by
     * Jackson: `TopologiBroadcaster` calls this every few seconds and just forwards the text, so
     * leaving it untouched keeps it identical to what Python sent.
     */
    public String getTopologiRaw() {
        return client.get()
                .uri("/topologi")
                .retrieve()
                .body(String.class);
    }

    /**
     * Same content as {@link #getTopologiRaw()} but parsed into `Object`. Used by the REST
     * `/api/topologi` fallback for browsers without WebSocket and for the first page load; called
     * rarely, so the parsing cost is fine.
     */
    public Object getTopologi() {
        return client.get()
                .uri("/topologi")
                .retrieve()
                .body(Object.class);
    }

    /**
     * Dashboard summary figures (devices up/down, services, incidents, rate) in one request.
     * Failures propagate to the caller, which decides which cards to keep showing.
     */
    public Object getRingkasDashboard() {
        return client.get()
                .uri("/dashboard/ringkas")
                .retrieve()
                .body(Object.class);
    }

    /**
     * File transfers over SFTP: who fetched what. The only source on the Traffic page that names a
     * person rather than an IP address (names come from LDAP and survive DHCP changes).
     */
    public Object getTrafficBerkas(String period) {
        return client.get()
                .uri("/traffic/berkas?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    /** Traffic anomaly findings. All scoring happens in Python. */
    public Object getTrafficAnomali(String period) {
        return client.get()
                .uri("/traffic/anomali?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    public Object getTraffic(String period) {
        return client.get()
                .uri("/traffic?period=" + period)
                .retrieve()
                .body(Object.class);
    }

    /**
     * Device configuration snapshot history (read side). These three methods only READ; none sends
     * changes to a device.
     */
    public Object getKonfigDaftar() {
        return client.get().uri("/konfig").retrieve().body(Object.class);
    }

    /**
     * Compliance findings on each device's latest snapshot. All evaluation is in Python so there is
     * only one answer to "is this device safe".
     */
    public Object getKonfigKepatuhan() {
        return client.get().uri("/konfig/kepatuhan").retrieve().body(Object.class);
    }

    /** Identity verdict per device. All weighing happens in Python. */
    public Object getIdentitas() {
        return client.get().uri("/identitas").retrieve().body(Object.class);
    }

    public Object getKonfigIsi(int snapshotId) {
        return client.get().uri("/konfig/" + snapshotId)
                .retrieve().body(Object.class);
    }

    /**
     * Configuration command catalog for a device. Neither command method below sends anything: one
     * reads the catalog, the other builds the command text and returns it for review.
     */
    public Object getPerintahKatalog(int deviceId) {
        return client.get().uri("/devices/" + deviceId + "/perintah")
                .retrieve().body(Object.class);
    }

    /** Builds the command and returns what WOULD be sent. Uses POST because it takes a request body, not because it changes anything. */
    public Object postPerintahPratinjau(int deviceId, java.util.Map<String, Object> isi) {
        return client.post()
                .uri("/devices/" + deviceId + "/perintah/pratinjau")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(isi)
                .retrieve()
                .body(Object.class);
    }

    /**
     * SENDS a change to a real device. Unlike `postPerintahPratinjau` this changes state outside NSM,
     * so `sungguhan` is passed through as given (Python's default is "send nothing"). The timeout
     * follows the client setting: a send installs a safety net, opens a session, sends, then verifies the device still
     * answers, which can take over ten seconds; cutting it short would leave `reload` armed.
     */
    public Object postPerintahKirim(int deviceId, java.util.Map<String, Object> isi) {
        return client.post()
                .uri("/devices/" + deviceId + "/perintah/kirim")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(isi)
                .retrieve()
                .body(Object.class);
    }

    public Object postPerintahPutuskan(int deviceId, java.util.Map<String, Object> isi) {
        return client.post()
                .uri("/devices/" + deviceId + "/perintah/putuskan")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(isi)
                .retrieve()
                .body(Object.class);
    }

    /** `write memory`: after this, a reload no longer restores the previous state. */
    public Object postPerintahSimpan(int deviceId, java.util.Map<String, Object> isi) {
        return client.post()
                .uri("/devices/" + deviceId + "/perintah/simpan")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(isi)
                .retrieve()
                .body(Object.class);
    }

    public Object getKonfigBeda(int snapshotId) {
        return client.get().uri("/konfig/" + snapshotId + "/beda")
                .retrieve().body(Object.class);
    }

    public Object getKonfigBelumDisimpan(int snapshotId) {
        return client.get().uri("/konfig/" + snapshotId + "/belum-disimpan")
                .retrieve().body(Object.class);
    }

    /** NSM's own health: each poller job, the database, and backups. The verdict is computed in Python (kesehatan.py). */
    public Object getKesehatan() {
        return client.get()
                .uri("/kesehatan")
                .retrieve()
                .body(Object.class);
    }

    /**
     * LDAP directory copy: people, titles, groups. Read-only at every layer; Python reads the copy
     * (`orang_ldap`) synced by the poller and never connects to the directory per request.
     */
    public Object getLdapDirektori() {
        return client.get()
                .uri("/ldap/direktori")
                .retrieve()
                .body(Object.class);
    }

    // Source of truth: Java forwards as-is; validation and rendering are in Python (`sot/katalog.py`,
    // `sot/render.py`). No call here touches a device.

    public Object getSotKatalog(String platform) {
        String uri = platform != null && !platform.isBlank()
                ? "/sot/katalog?platform=" + platform : "/sot/katalog";
        return client.get().uri(uri).retrieve().body(Object.class);
    }

    public Object getSotRingkasan() {
        return client.get().uri("/sot").retrieve().body(Object.class);
    }

    public Object getSotDevice(int deviceId) {
        return client.get().uri("/sot/" + deviceId).retrieve().body(Object.class);
    }

    /** Save a single-key intent value. May be partial. */
    public Object postSotNilai(int deviceId, java.util.Map<String, Object> isi) {
        return client.post().uri("/sot/" + deviceId + "/nilai")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(isi).retrieve().body(Object.class);
    }

    public Object postSotInterface(int deviceId, java.util.Map<String, Object> isi) {
        return client.post().uri("/sot/" + deviceId + "/interface")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(isi).retrieve().body(Object.class);
    }

    public Object postSotVlan(int deviceId, java.util.Map<String, Object> isi) {
        return client.post().uri("/sot/" + deviceId + "/vlan")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(isi).retrieve().body(Object.class);
    }

    /** Reconcile ALL static routes of this device's intended state. */
    public Object postSotRute(int deviceId, java.util.Map<String, Object> isi) {
        return client.post().uri("/sot/" + deviceId + "/rute")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(isi).retrieve().body(Object.class);
    }

    /** Renders stored intent as intended configuration text. Does not touch the device. */
    public Object getSotRender(int deviceId) {
        return client.get().uri("/sot/" + deviceId + "/render")
                .retrieve().body(Object.class);
    }

    public Object getSotRiwayat(int deviceId) {
        return client.get().uri("/sot/" + deviceId + "/riwayat")
                .retrieve().body(Object.class);
    }

    // Drift detection: compares intent with the latest configuration snapshot. Reads NSM's own database only.

    public Object getDriftRingkasan() {
        return client.get().uri("/drift").retrieve().body(Object.class);
    }

    public Object getDriftDevice(int deviceId) {
        return client.get().uri("/drift/" + deviceId).retrieve().body(Object.class);
    }

    // Automation guardrail: the mandatory gate for future remediation. Read-only on the web side;
    // no endpoint executes `pagar_otomasi.putuskan()`.

    public Object getPagarStatus() {
        return client.get().uri("/pagar/status").retrieve().body(Object.class);
    }

    public Object getPagarRiwayat() {
        return client.get().uri("/pagar/riwayat").retrieve().body(Object.class);
    }

    // Incident correlation: one outage rather than one symptom. Python merges symptoms using the
    // dependency graph; Java only forwards JSON and computes no root-cause or MTTR figures.

    public Object getInsiden(int jam) {
        return client.get().uri("/insiden?jam=" + jam)
                .retrieve().body(Object.class);
    }

    public Object getInsidenDetail(int id) {
        return client.get().uri("/insiden/" + id)
                .retrieve().body(Object.class);
    }

    // Lightweight learning (insights): read-only. Baselines, pattern mining, and forecasts are all computed in Python.

    public Object getBaseline() {
        return client.get().uri("/baseline").retrieve().body(Object.class);
    }

    public Object getPolaLog(int jam) {
        return client.get().uri("/pola-log?jam=" + jam)
                .retrieve().body(Object.class);
    }

    /**
     * Three dashboard charts next to the topology map (hourly availability, device messages per
     * hour, storage capacity) in one request, so a partial failure cannot show some panels and
     * silently omit others.
     */
    public Object getDasborGrafik(int jam) {
        return client.get().uri("/dasbor/grafik?jam=" + jam)
                .retrieve().body(Object.class);
    }

    /**
     * Raw syslog stream for the Syslog page, in one request for the whole page for the same reason
     * as the dashboard charts.
     */
    public Object getSyslogDasbor(int jam) {
        return client.get().uri("/syslog/dasbor?jam=" + jam)
                .retrieve().body(Object.class);
    }

    public Object getSyslogPesan(int jam, Integer deviceId, String tag,
                                 boolean hanyaPenting, String cari,
                                 int halaman, int perHalaman) {
        StringBuilder u = new StringBuilder("/syslog/pesan?jam=").append(jam)
                .append("&halaman=").append(halaman)
                .append("&per_halaman=").append(perHalaman);
        if (deviceId != null) {
            u.append("&device_id=").append(deviceId);
        }
        if (tag != null && !tag.isBlank()) {
            u.append("&tag=").append(URLEncoder.encode(tag, StandardCharsets.UTF_8));
        }
        if (hanyaPenting) {
            u.append("&penting=1");
        }
        if (cari != null && !cari.isBlank()) {
            u.append("&cari=").append(URLEncoder.encode(cari, StandardCharsets.UTF_8));
        }
        return client.get().uri(u.toString()).retrieve().body(Object.class);
    }

    /**
     * Bandwidth saturation and latency trend. The error budget is excluded because it is much more
     * expensive and has its own endpoint.
     */
    public Object getPrakiraan() {
        return client.get().uri("/prakiraan").retrieve().body(Object.class);
    }

    /** C3c -- laju habisnya anggaran galat. Lambat; dimuat terpisah. */
    public Object getPrakiraanAnggaran() {
        return client.get().uri("/prakiraan/anggaran")
                .retrieve().body(Object.class);
    }

    /** C4: SOC agent proposals, each with its guardrail verdict. */
    public Object getAgenSoc(int jam) {
        return client.get().uri("/agen-soc?jam=" + jam)
                .retrieve().body(Object.class);
    }

    // -------------------------------------------------------------------
    // PAKET D -- multi-tenancy.
    // -------------------------------------------------------------------

    /** Daftar tenant berikut pemakaian kuotanya. */
    public Object getTenant() {
        return client.get().uri("/tenant").retrieve().body(Object.class);
    }

    // Device discovery: Java forwards as-is; the scan guards and all decisions are in Python.
    // `postPenemuanSetujui` is the only path from scan results to the `devices` table, and the
    // device it creates is inactive.

    public Object getPenemuan(String status) {
        return client.get()
                .uri("/penemuan?status=" + URLEncoder.encode(
                        status == null ? "baru" : status, StandardCharsets.UTF_8))
                .retrieve()
                .body(Object.class);
    }

    /**
     * POSTs to Python and returns the status together with the body, without throwing on 4xx.
     * The scan guard rejects with a 400 and a human-readable reason (for example for a public
     * range); passing status and body through as-is is simpler than catching the exception and
     * re-parsing the JSON in the controller.
     */
    private org.springframework.http.ResponseEntity<Object> kirim(
            String jalur, java.util.Map<String, Object> isi) {
        return client.post()
                .uri(jalur)
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(isi)
                .retrieve()
                .onStatus(org.springframework.http.HttpStatusCode::isError,
                          (permintaan, balasan) -> {  })
                .toEntity(Object.class);
    }

    /** Scan one network. SENDS PACKETS to every address; see the audit. */
    public org.springframework.http.ResponseEntity<Object> postPenemuanPindai(
            java.util.Map<String, Object> isi) {
        return kirim("/penemuan/pindai", isi);
    }

    public org.springframework.http.ResponseEntity<Object> postPenemuanSetujui(
            int temuanId, java.util.Map<String, Object> isi) {
        return kirim("/penemuan/" + temuanId + "/setujui", isi);
    }

    public org.springframework.http.ResponseEntity<Object> postPenemuanAbaikan(int temuanId) {
        return kirim("/penemuan/" + temuanId + "/abaikan", java.util.Map.of());
    }
}
