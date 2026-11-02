package id.bsp.frontend.controller;

import id.bsp.frontend.dto.DeviceDto;
import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseBody;

import java.util.List;

@Controller
public class DashboardController {

    private final NetmonApiClient api;
    private final AuditService audit;

    public DashboardController(NetmonApiClient api, AuditService audit) {
        this.api = api;
        this.audit = audit;
    }

    @GetMapping("/")
    public String dashboard(Model model, Authentication auth) {
        model.addAttribute("username", auth.getName());
        boolean isAdmin = auth.getAuthorities().stream()
                .anyMatch(a -> a.getAuthority().equals("ROLE_ADMIN"));
        model.addAttribute("isAdmin", isAdmin);
        return "dashboard";
    }

    @GetMapping("/api/devices")
    @ResponseBody
    public List<DeviceDto> devices() {
        return api.getDevices();
    }

    /**
     * Three charts beside the topology map.
     * The time window is capped server-side, like Insiden, Wawasan and Syslog; otherwise `?jam=99999999` would make Python scan the entire history for one page request.
     */
    @GetMapping("/api/dasbor/grafik")
    @ResponseBody
    public Object dasborGrafik(
            @org.springframework.web.bind.annotation.RequestParam(defaultValue = "24") int jam) {
        int aman = Math.max(1, Math.min(jam, 720));
        try {
            return api.getDasborGrafik(aman);
        } catch (org.springframework.web.client.RestClientResponseException e) {
            return org.springframework.http.ResponseEntity.status(e.getStatusCode())
                    .body(java.util.Map.of("ok", false, "ditolak", e.getMessage()));
        }
    }

    /**
     * Latest traffic rate of all devices, for the bandwidth row on the cards.
     * Not audited: it follows the dashboard's 5-second refresh. Requested separately from /api/devices so its failure does not take down the cards; device up/down matters more than traffic numbers.
     */
    /** Fault diagnosis. Part of the dashboard refresh, so not audited. Separate from /api/devices for the same reason as bandwidth: up/down status matters more than the explanation. */
    @GetMapping("/api/diagnosis")
    @ResponseBody
    public Object diagnosis() {
        return api.getDiagnosis();
    }

    /**
     * Topology map over plain REST: a FALLBACK, not the main path.
     * The main path is WebSocket (`/ws/topologi`, package `ws`), pushing updates every two seconds. `js/topologi.js` calls this endpoint once before the WebSocket connects, and repeatedly if the WebSocket cannot connect at all (e.g. a proxy blocking the protocol upgrade). Not audited, as with /api/diagnosis.
     */
    @GetMapping("/api/topologi")
    @ResponseBody
    public Object topologi() {
        return api.getTopologi();
    }

    @GetMapping("/api/devices/bandwidth-terkini")
    @ResponseBody
    public Object bandwidthTerkini() {
        return api.getBandwidthTerkini();
    }

    /** Dashboard summary strip: one request for all figures. Separate from /api/devices so that if Python stops answering, only the summary is lost, not the device up/down cards. */
    @GetMapping("/api/dashboard/ringkas")
    @ResponseBody
    public Object ringkasDashboard() {
        return api.getRingkasDashboard();
    }

    /** Dedicated page for SSH data collection of one device. A separate page because the content (memory, disk, CPU load, processes, login sessions) is large. The page calls `/api/devices/{id}/info`, where the audit is recorded, so the data fetch is audited, not just opening the page. */
    @GetMapping("/device/{id}/ssh")
    public String detailSsh(@PathVariable int id, Model model, Authentication auth) {
        model.addAttribute("username", auth.getName());
        boolean isAdmin = auth.getAuthorities().stream()
                .anyMatch(a -> a.getAuthority().equals("ROLE_ADMIN"));
        model.addAttribute("isAdmin", isAdmin);
        model.addAttribute("deviceId", id);
        return "device_ssh";
    }

    /**
     * Pause / resume monitoring of a device.
     * The only write path in the whole app, so its guards are explicit:
     *   - ROLE_ADMIN only (SecurityConfig)
     *   - POST with CSRF token required
     *   - always audited, success or failure
     * Only NSM settings change; no command is sent to the device.
     */
    @PostMapping("/api/devices/{id}/aktif")
    @ResponseBody
    public Object setAktif(@PathVariable int id,
                           @RequestBody java.util.Map<String, Object> badan,
                           HttpServletRequest request,
                           java.security.Principal siapa) {
        boolean aktif = Boolean.TRUE.equals(badan.get("aktif"));
        // Pause reason. Without it a legitimate pause could not be told apart from a forgotten one.
        Object a = badan.get("alasan");
        String alasan = (a == null) ? null : String.valueOf(a);
        // The username comes from the SESSION, not the request body, which anyone can forge.
        String oleh = (siapa != null) ? siapa.getName() : null;
        try {
            Object hasil = api.setDeviceAktif(id, aktif, alasan, oleh);
            audit.logRequest(aktif ? AuditService.DEVICE_LANJUT : AuditService.DEVICE_JEDA,
                    String.valueOf(id),
                    aktif ? "melanjutkan pemantauan device"
                          : ("menjeda pemantauan device"
                             + (alasan != null && !alasan.isBlank()
                                ? " — alasan: " + alasan : " — tanpa alasan")),
                    true, request);
            return hasil;
        } catch (Exception e) {
            audit.logRequest(aktif ? AuditService.DEVICE_LANJUT : AuditService.DEVICE_JEDA,
                    String.valueOf(id), "gagal: " + e.getMessage(), false, request);
            throw e;
        }
    }

    /** Turn email notifications on/off. Same guards as the pause button. */
    @PostMapping("/api/devices/{id}/penting")
    @ResponseBody
    public Object setPenting(@PathVariable int id,
                             @RequestBody java.util.Map<String, Boolean> badan,
                             HttpServletRequest request) {
        boolean penting = Boolean.TRUE.equals(badan.get("penting"));
        try {
            Object hasil = api.setDevicePenting(id, penting);
            audit.logRequest(AuditService.NOTIF_TOGGLE, String.valueOf(id),
                    penting ? "menyalakan notifikasi email device"
                            : "mematikan notifikasi email device",
                    true, request);
            return hasil;
        } catch (Exception e) {
            audit.logRequest(AuditService.NOTIF_TOGGLE, String.valueOf(id),
                    "gagal: " + e.getMessage(), false, request);
            throw e;
        }
    }

    @GetMapping("/api/devices/{id}/info")
    @ResponseBody
    public Object deviceInfo(@PathVariable int id, HttpServletRequest request) {
        // Audit: who viewed which device's SSH details (target = device id, for per-device filtering).
        audit.logRequest(AuditService.VIEW_DEVICE, String.valueOf(id),
                "lihat Detail/SSH info device", true, request);
        return api.getDeviceInfo(id);
    }
}
