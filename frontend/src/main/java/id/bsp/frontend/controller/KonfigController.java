package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.client.RestClientResponseException;
import tools.jackson.databind.ObjectMapper;

import java.util.Map;

/**
 * CONFIGURATION HISTORY page: what changed on a device, and when.
 * Read-only: no endpoint in this class sends changes to a device. The poller stores a snapshot only when content changes, so one row is one real change.
 * ADMIN only: content is masked before storage (passwords, SNMP community, pre-shared keys) but configs still reveal network layout.
 * Java computes nothing; diff, masking and the "changed or not" decision are done by Python.
 */
@Controller
public class KonfigController {

    private final NetmonApiClient api;
    private final AuditService audit;
    private final ObjectMapper mapper;

    public KonfigController(NetmonApiClient api, AuditService audit, ObjectMapper mapper) {
        this.api = api;
        this.audit = audit;
        this.mapper = mapper;
    }

    /** Python's real refusal reason (`{"ditolak": "..."}`) from the raw 409 body. `RestClient.retrieve()` throws for any non-2xx status, which would otherwise lose the reason and skip the Audit Log row. */
    private String ambilDitolak(RestClientResponseException e) {
        try {
            Map<?, ?> badan = mapper.readValue(e.getResponseBodyAsString(), Map.class);
            Object d = badan.get("ditolak");
            return d != null ? String.valueOf(d) : e.getMessage();
        } catch (Exception parseErr) {
            return e.getMessage();
        }
    }

    /** The Audit Log `detail` column is limited to 512 characters; truncate here rather than letting the database cut mid-word or throw. */
    private static String potong(String s, int n) {
        if (s == null) return null;
        return s.length() > n ? s.substring(0, n) + "..." : s;
    }

    /** CONFIG HOME. Shows the answer of each of the five sections as cards; the evidence lives on the five pages below. The address `/admin/konfig` is unchanged because it appears in navigation, tests and saved links. */
    @GetMapping("/admin/konfig")
    public String halaman(Model model, HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_KONFIG, null,
                "buka beranda Konfigurasi", true, request);
        return "konfig";
    }

    // Five content pages, all under `/admin/**`, so ADMIN protection applies from SecurityConfig without new rules. Each page is audited with a description naming its section, so the Audit Log can tell history viewers from command-builder users.

    @GetMapping("/admin/konfig/perintah")
    public String halamanPerintah(HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_KONFIG, null,
                "buka halaman Susun Perintah Konfigurasi", true, request);
        return "konfig_perintah";
    }

    @GetMapping("/admin/konfig/kepatuhan")
    public String halamanKepatuhan(HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_KONFIG, null,
                "buka halaman Kepatuhan Konfigurasi", true, request);
        return "konfig_kepatuhan";
    }

    @GetMapping("/admin/konfig/identitas")
    public String halamanIdentitas(HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_KONFIG, null,
                "buka halaman Identitas Perangkat", true, request);
        return "konfig_identitas";
    }

    @GetMapping("/admin/konfig/firewall")
    public String halamanFirewall(HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_KONFIG, null,
                "buka halaman Firewall", true, request);
        return "konfig_firewall";
    }

    @GetMapping("/admin/konfig/potret")
    public String halamanPotret(HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_KONFIG, null,
                "buka halaman Potret Konfigurasi", true, request);
        return "konfig_potret";
    }

    /** Snapshot list. Not audited: the page refreshes itself; opening the page is audited. */
    @GetMapping("/api/konfig")
    @ResponseBody
    public Object daftar() {
        return api.getKonfigDaftar();
    }

    /**
     * Firewall rules of each Linux device.
     * Read-only. No NSM endpoint changes firewall rules; if one is added it must require explicit per-change permission, like sending config commands to routers, not a POST method added beside this one.
     */
    @GetMapping("/api/firewall")
    @ResponseBody
    public Object firewall() {
        return api.getFirewall();
    }

    /**
     * Block one IP in a device's firewall (auto-ban). WRITES to the device.
     * ADMIN only (under /admin/**). The blocker's name comes from the SESSION, not the request body. Allowlist refusals come from Python and are still AUDITED.
     */
    @PostMapping("/api/firewall/blokir")
    @ResponseBody
    public Object firewallBlokir(@RequestBody Map<String, Object> isi,
                                 HttpServletRequest request,
                                 java.security.Principal siapa) {
        isi.put("oleh", siapa != null ? siapa.getName() : "?");
        Object hasil = api.postFirewallBlokir(isi);
        boolean ok = (hasil instanceof Map<?, ?> m) && Boolean.TRUE.equals(m.get("ok"));
        boolean ditolak = (hasil instanceof Map<?, ?> m) && Boolean.TRUE.equals(m.get("ditolak"));
        audit.logRequest(AuditService.FIREWALL_BLOKIR, String.valueOf(isi.get("ip")),
                "blokir " + isi.get("ip") + (ditolak ? " (DITOLAK pengaman allowlist)" : ""),
                ok, request);
        return hasil;
    }

    @PostMapping("/api/firewall/buka-blokir")
    @ResponseBody
    public Object firewallBukaBlokir(@RequestBody Map<String, Object> isi,
                                     HttpServletRequest request,
                                     java.security.Principal siapa) {
        isi.put("oleh", siapa != null ? siapa.getName() : "?");
        Object hasil = api.postFirewallBukaBlokir(isi);
        boolean ok = !(hasil instanceof Map<?, ?> m) || !Boolean.FALSE.equals(m.get("ok"));
        audit.logRequest(AuditService.FIREWALL_BUKA_BLOKIR, String.valueOf(isi.get("ip")),
                "buka blokir " + isi.get("ip"), ok, request);
        return hasil;
    }

    /** Block one IP in the router ACL: the SECOND layer for Site B, separate from `/api/firewall/blokir` (ufw). One IP may deliberately be blocked in both layers; see `penjaga_aksi.block_acl` (Python). */
    @PostMapping("/api/firewall/blokir-acl")
    @ResponseBody
    public Object firewallBlokirAcl(@RequestBody Map<String, Object> isi,
                                    HttpServletRequest request,
                                    java.security.Principal siapa) {
        isi.put("oleh", siapa != null ? siapa.getName() : "?");
        Object hasil = api.postFirewallBlokirAcl(isi);
        boolean ok = (hasil instanceof Map<?, ?> m) && Boolean.TRUE.equals(m.get("ok"));
        boolean ditolak = (hasil instanceof Map<?, ?> m) && Boolean.TRUE.equals(m.get("ditolak"));
        audit.logRequest(AuditService.FIREWALL_ACL_BLOKIR, String.valueOf(isi.get("ip")),
                "blokir ACL " + isi.get("ip") + (ditolak ? " (DITOLAK pengaman allowlist)" : ""),
                ok, request);
        return hasil;
    }

    /**
     * Compliance findings on each device's latest snapshot.
     * Registered before `/api/konfig/{id}` on purpose: Spring prefers literal paths anyway, but FastAPI matches by registration order, so both sides use the same order. Java only forwards; no judgment here.
     */
    @GetMapping("/api/konfig/kepatuhan")
    @ResponseBody
    public Object kepatuhan() {
        return api.getKonfigKepatuhan();
    }

    /** Identity verdict of each device with its stored marker. Java weighs nothing: the verdict decides whether a device may be written to, so it lives in Python only. */
    @GetMapping("/api/identitas")
    @ResponseBody
    public Object identitas() {
        return api.getIdentitas();
    }

    /** Full content of one snapshot. */
    @GetMapping("/api/konfig/{id}")
    @ResponseBody
    public Object isi(@PathVariable int id) {
        return api.getKonfigIsi(id);
    }

    /** What changed in this snapshot versus the previous one. */
    @GetMapping("/api/konfig/{id}/beda")
    @ResponseBody
    public Object beda(@PathVariable int id) {
        return api.getKonfigBeda(id);
    }

    /** Which lines would be lost if the device were restarted. */
    @GetMapping("/api/konfig/{id}/belum-disimpan")
    @ResponseBody
    public Object belumDisimpan(@PathVariable int id) {
        return api.getKonfigBelumDisimpan(id);
    }

    // Command catalog and preview. Neither sends anything to a device.

    /** Commands available for a device. */
    @GetMapping("/api/konfig/perintah/{deviceId}")
    @ResponseBody
    public Object katalogPerintah(@PathVariable int deviceId) {
        return api.getPerintahKatalog(deviceId);
    }

    /**
     * Build the command and show what WOULD be sent.
     * Audited even though nothing is sent: building a config command is an intent worth recording, and rejected attempts are the most useful rows in the Audit Log.
     */
    @PostMapping("/api/konfig/perintah/{deviceId}/pratinjau")
    @ResponseBody
    public Object pratinjauPerintah(@PathVariable int deviceId,
                                    @RequestBody Map<String, Object> isi,
                                    HttpServletRequest request) {
        Object hasil = api.postPerintahPratinjau(deviceId, isi);
        boolean ok = (hasil instanceof Map<?, ?> m)
                && Boolean.TRUE.equals(m.get("ok"));
        audit.logRequest(AuditService.PERINTAH_PRATINJAU, String.valueOf(deviceId),
                "pratinjau perintah '" + isi.get("perintah_id") + "'"
                        + (ok ? "" : " (ditolak validasi)"),
                ok, request);
        return hasil;
    }

    /**
     * SEND a change to a real device.
     * ADMIN only; previews are open to anyone who can view the page. Audited once, with the result, since the call waits for the device to answer; failures are recorded too.
     */
    @PostMapping("/api/konfig/perintah/{deviceId}/kirim")
    @ResponseBody
    public Object kirimPerintah(@PathVariable int deviceId,
                                @RequestBody Map<String, Object> isi,
                                HttpServletRequest request,
                                java.security.Principal siapa) {
        // The sender name comes from the SESSION, not the request body; a forgeable audit trail is worse than none.
        isi.put("oleh", siapa != null ? siapa.getName() : "?");

        Object hasil;
        try {
            hasil = api.postPerintahKirim(deviceId, isi);
        } catch (RestClientResponseException e) {
            // Python refuses BEFORE trying anything (Ditolak -> 409), e.g. the guard that an interface is used by NSM itself (docs/POSTMORTEM-R1.md). Without this block the user gets a generic error and the Audit Log gets no row.
            String ditolak = ambilDitolak(e);
            audit.logRequest(AuditService.PERINTAH_KIRIM, String.valueOf(deviceId),
                    "kirim perintah '" + isi.get("perintah_id") + "' DITOLAK: "
                            + potong(ditolak, 400),
                    false, request);
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("ok", false, "ditolak", ditolak));
        }

        boolean terkirim = (hasil instanceof Map<?, ?> m)
                && Boolean.TRUE.equals(m.get("terkirim"));
        // Record the real error reason, not just a "(not sent)" boolean, so the original error text is not lost.
        String galat = (!terkirim && hasil instanceof Map<?, ?> m
                && m.get("galat") != null) ? String.valueOf(m.get("galat")) : null;
        audit.logRequest(AuditService.PERINTAH_KIRIM, String.valueOf(deviceId),
                "kirim perintah '" + isi.get("perintah_id") + "'"
                        + (terkirim ? ""
                           : " (tidak terkirim" + (galat != null
                               ? ": " + potong(galat, 380) : "") + ")"),
                terkirim, request);
        return hasil;
    }

    /** Keep or revert a change that was just sent. */
    @PostMapping("/api/konfig/perintah/{deviceId}/putuskan")
    @ResponseBody
    public Object putuskanPerintah(@PathVariable int deviceId,
                                   @RequestBody Map<String, Object> isi,
                                   HttpServletRequest request) {
        Object hasil;
        try {
            hasil = api.postPerintahPutuskan(deviceId, isi);
        } catch (RestClientResponseException e) {
            // As with `kirimPerintah`: a Python refusal (e.g. GNS3 API restore failing in `batalkan_sekarang`) must not become a generic error or a missing Audit Log row.
            String ditolak = ambilDitolak(e);
            audit.logRequest(AuditService.PERINTAH_PUTUSKAN, String.valueOf(deviceId),
                    "putuskan: " + isi.get("tindakan") + " DITOLAK: "
                            + potong(ditolak, 400),
                    false, request);
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("ok", false, "ditolak", ditolak));
        }
        boolean ok = !(hasil instanceof Map<?, ?> m)
                || !Boolean.FALSE.equals(m.get("ok"));
        audit.logRequest(AuditService.PERINTAH_PUTUSKAN, String.valueOf(deviceId),
                "putuskan: " + isi.get("tindakan"), ok, request);
        return hasil;
    }

    /**
     * `write memory`.
     * Audited separately from `kirim`: afterwards a device restart no longer restores the previous state, so the way back is gone and deserves its own Audit Log row.
     */
    @PostMapping("/api/konfig/perintah/{deviceId}/simpan")
    @ResponseBody
    public Object simpanPerintah(@PathVariable int deviceId,
                                 @RequestBody(required = false) Map<String, Object> isi,
                                 HttpServletRequest request) {
        Object hasil = api.postPerintahSimpan(deviceId,
                isi != null ? isi : new java.util.HashMap<>());
        boolean ok = !(hasil instanceof Map<?, ?> m)
                || !Boolean.FALSE.equals(m.get("ok"));
        audit.logRequest(AuditService.PERINTAH_SIMPAN, String.valueOf(deviceId),
                "write memory", ok, request);
        return hasil;
    }
}
