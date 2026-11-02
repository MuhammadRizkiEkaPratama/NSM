package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;

/**
 * Report page (device availability and outage history). Java computes nothing; all figures
 * come from Python (report_service.py). Open to Admin and Viewer (read-only).
 * Unlike the Audit Log (account activity, MySQL), Report shows device state (SQLite, Python side).
 */
@Controller
public class ReportController {

    private final NetmonApiClient api;
    private final AuditService audit;

    public ReportController(NetmonApiClient api, AuditService audit) {
        this.api = api;
        this.audit = audit;
    }

    @GetMapping("/report")
    public String report(@RequestParam(defaultValue = "24h") String period,
                         Model model, Authentication auth,
                         HttpServletRequest request) {
        model.addAttribute("username", auth.getName());
        boolean isAdmin = auth.getAuthorities().stream()
                .anyMatch(a -> a.getAuthority().equals("ROLE_ADMIN"));
        model.addAttribute("isAdmin", isAdmin);
        model.addAttribute("period", bersihkanPeriode(period));

        audit.logRequest(AuditService.VIEW_REPORT, null,
                "buka halaman Report (periode " + bersihkanPeriode(period) + ")",
                true, request);
        return "report";
    }

    /** Per-device history page. */
    @GetMapping("/report/device/{id}")
    public String deviceReport(@PathVariable int id,
                               @RequestParam(defaultValue = "24h") String period,
                               Model model, Authentication auth,
                               HttpServletRequest request) {
        model.addAttribute("username", auth.getName());
        boolean isAdmin = auth.getAuthorities().stream()
                .anyMatch(a -> a.getAuthority().equals("ROLE_ADMIN"));
        model.addAttribute("isAdmin", isAdmin);
        model.addAttribute("deviceId", id);
        model.addAttribute("period", bersihkanPeriode(period));

        audit.logRequest(AuditService.VIEW_HISTORY, String.valueOf(id),
                "buka halaman riwayat device (periode " + bersihkanPeriode(period) + ")",
                true, request);
        return "report_device";
    }

    /** Print-ready report page, separate from the on-screen Report page (no buttons or progress bars). */
    @GetMapping("/report/cetak")
    public String cetak(@RequestParam(defaultValue = "24h") String period,
                        Model model, Authentication auth,
                        HttpServletRequest request) {
        model.addAttribute("username", auth.getName());
        model.addAttribute("period", bersihkanPeriode(period));
        audit.logRequest(AuditService.EXPORT_REPORT, null,
                "buka laporan siap cetak (periode " + bersihkanPeriode(period) + ")",
                true, request);
        return "report_cetak";
    }


    /**
     * Streams a CSV file from Python to the browser as a download. The file name is built by Python
     * and sent in the {@code X-Nama-Berkas} header so naming stays in one place.
     */
    private static final String XLSX =
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    private static final String DOCX =
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

    private ResponseEntity<byte[]> unduhan(ResponseEntity<byte[]> dariPython,
                                           String namaCadangan) {
        return unduhan(dariPython, namaCadangan, XLSX);
    }

    private ResponseEntity<byte[]> unduhan(ResponseEntity<byte[]> dariPython,
                                           String namaCadangan, String tipe) {
        String nama = dariPython.getHeaders().getFirst("X-Nama-Berkas");
        if (nama == null || nama.isBlank()) nama = namaCadangan;
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_TYPE, tipe)
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=\"" + nama + "\"")
                .body(dariPython.getBody());
    }

    @GetMapping("/report/export")
    @ResponseBody
    public ResponseEntity<byte[]> exportReport(
            @RequestParam(defaultValue = "24h") String period,
            Authentication auth, HttpServletRequest request) {
        String p = bersihkanPeriode(period);
        audit.logRequest(AuditService.EXPORT_REPORT, null,
                "unduh laporan Excel (periode " + p + ")", true, request);
        return unduhan(api.exportReport(p, auth.getName()),
                       "laporan-availability.xlsx");
    }

    @GetMapping("/report/export-word")
    @ResponseBody
    public ResponseEntity<byte[]> exportReportWord(
            @RequestParam(defaultValue = "24h") String period,
            Authentication auth, HttpServletRequest request) {
        String p = bersihkanPeriode(period);
        audit.logRequest(AuditService.EXPORT_REPORT, null,
                "unduh laporan Word (periode " + p + ")", true, request);
        return unduhan(api.exportReportWord(p, auth.getName()),
                       "laporan-availability.docx", DOCX);
    }

    @GetMapping("/report/device/{id}/export")
    @ResponseBody
    public ResponseEntity<byte[]> exportRiwayat(
            @PathVariable int id,
            @RequestParam(defaultValue = "24h") String period,
            Authentication auth, HttpServletRequest request) {
        String p = bersihkanPeriode(period);
        audit.logRequest(AuditService.EXPORT_REPORT, String.valueOf(id),
                "unduh riwayat Excel device (periode " + p + ")", true, request);
        return unduhan(api.exportRiwayat(id, p, auth.getName()),
                       "riwayat-device.xlsx");
    }


    @GetMapping("/api/report/summary")
    @ResponseBody
    public Object summary(@RequestParam(defaultValue = "24h") String period) {
        return api.getReportSummary(bersihkanPeriode(period));
    }

    @GetMapping("/api/report/availability")
    @ResponseBody
    public Object availability(@RequestParam(defaultValue = "24h") String period) {
        return api.getReportAvailability(bersihkanPeriode(period));
    }

    @GetMapping("/api/report/slo")
    @ResponseBody
    public Object slo() {
        return api.getReportSlo();
    }

    @GetMapping("/api/report/sparkline")
    @ResponseBody
    public Object sparkline(@RequestParam(defaultValue = "24h") String period) {
        return api.getReportSparkline(bersihkanPeriode(period));
    }

    @GetMapping("/api/devices/{id}/history")
    @ResponseBody
    public Object history(@PathVariable int id,
                          @RequestParam(defaultValue = "24h") String period,
                          @RequestParam(defaultValue = "false") boolean bg,
                          HttpServletRequest request) {
        // Audited only when the user actually opens the history (bg=false); the 10-second auto-refresh
        // uses bg=true so the audit log is not flooded.
        if (!bg) {
            audit.logRequest(AuditService.VIEW_HISTORY, String.valueOf(id),
                    "lihat riwayat gangguan device (periode " + bersihkanPeriode(period) + ")",
                    true, request);
        }
        return api.getDeviceHistory(id, bersihkanPeriode(period));
    }

    @GetMapping("/api/devices/{id}/bandwidth")
    @ResponseBody
    public Object bandwidth(@PathVariable int id,
                            @RequestParam(defaultValue = "24h") String period) {
        // Not audited: part of the device page's auto-refresh.
        return api.getDeviceBandwidth(id, bersihkanPeriode(period));
    }

    @GetMapping("/api/devices/{id}/chart")
    @ResponseBody
    public Object chart(@PathVariable int id,
                        @RequestParam(defaultValue = "60") int points) {
        // Caps the number of points so "?points=999999" cannot overload the backend (input validation).
        int aman = points;
        if (aman < 10) aman = 10;
        if (aman > 300) aman = 300;
        return api.getDeviceChart(id, aman);
    }

    @GetMapping("/api/devices/{id}/latest")
    @ResponseBody
    public Object latest(@PathVariable int id) {
        return api.getDeviceLatest(id);
    }

    @GetMapping("/api/devices/{id}/events")
    @ResponseBody
    public Object events(@PathVariable int id,
                         @RequestParam(defaultValue = "24h") String period) {
        return api.getDeviceEvents(id, bersihkanPeriode(period));
    }

    /**
     * Latest outage with cause, evidence chain, and suggested action. Separate from
     * /api/report/summary because it can be large and summary is polled every 10 seconds.
     * Not audited, to avoid flooding the Audit Log.
     */
    @GetMapping("/api/report/insiden-terakhir")
    @ResponseBody
    public Object insidenTerakhir() {
        return api.getInsidenTerakhir();
    }

    /** Period whitelist: input validation so raw URL values are not forwarded to the backend. */
    private String bersihkanPeriode(String period) {
        if (period == null) return "24h";
        switch (period) {
            case "1h":
            case "24h":
            case "7d":
            case "30d":
                return period;
            default:
                return "24h";
        }
    }
}
