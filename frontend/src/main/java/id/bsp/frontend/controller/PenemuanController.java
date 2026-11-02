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
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;

import java.util.Map;

/**
 * Device discovery: scan a subnet, identify devices by SNMP sysObjectID, and only offer them.
 * Scan results never enter the {@code devices} table on their own; the only path is the
 * "Approve" button, and the device it creates is inactive. Java makes no decisions here;
 * the scan guards (public ranges, ranges over 1024 addresses, typos) live in
 * {@code backend/penemuan.py}. All write paths are audited, including scans and rejected attempts,
 * because a scan sends packets to every address in the subnet.
 */
@Controller
public class PenemuanController {

    private final NetmonApiClient api;
    private final AuditService audit;

    public PenemuanController(NetmonApiClient api, AuditService audit) {
        this.api = api;
        this.audit = audit;
    }

    @GetMapping("/admin/konfig/penemuan")
    public String beranda(Model model, HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_PENEMUAN, null,
                "buka halaman Penemuan Perangkat", true, request);
        return "konfig_penemuan";
    }

    @GetMapping("/api/penemuan")
    @ResponseBody
    public Object daftar(@RequestParam(defaultValue = "baru") String status) {
        return api.getPenemuan(status);
    }

    /**
     * Scans one network. Python's status and response body are passed through as-is, including
     * the 400 rejection message, which is written for humans.
     */
    @PostMapping("/api/penemuan/pindai")
    @ResponseBody
    public ResponseEntity<Object> pindai(@RequestBody Map<String, Object> isi,
                                         HttpServletRequest request) {
        String jaringan = String.valueOf(isi.get("jaringan"));
        ResponseEntity<Object> balasan = api.postPenemuanPindai(isi);
        boolean ok = balasan.getStatusCode().is2xxSuccessful();
        audit.logRequest(AuditService.PENEMUAN_PINDAI, jaringan,
                ok ? "pindai " + jaringan + " -> " + jumlah(balasan) + " menjawab"
                   : "pindai " + jaringan + " DITOLAK: " + alasan(balasan),
                ok, request);
        return balasan;
    }

    /** Turns a finding into a device. The only path into {@code devices}; the device is created with {@code aktif=0}. */
    @PostMapping("/api/penemuan/{id}/setujui")
    @ResponseBody
    public ResponseEntity<Object> setujui(@PathVariable int id,
                                          @RequestBody Map<String, Object> isi,
                                          HttpServletRequest request) {
        ResponseEntity<Object> balasan = api.postPenemuanSetujui(id, isi);
        boolean ok = balasan.getStatusCode().is2xxSuccessful();
        audit.logRequest(AuditService.PENEMUAN_SETUJUI, String.valueOf(id),
                ok ? "temuan #" + id + " (" + medan(balasan, "ip_address") + ") jadi device \""
                     + isi.get("nama") + "\" -- dibuat BELUM AKTIF"
                   : "setujui temuan #" + id + " DITOLAK: " + alasan(balasan),
                ok, request);
        return balasan;
    }

    @PostMapping("/api/penemuan/{id}/abaikan")
    @ResponseBody
    public ResponseEntity<Object> abaikan(@PathVariable int id,
                                          HttpServletRequest request) {
        ResponseEntity<Object> balasan = api.postPenemuanAbaikan(id);
        boolean ok = balasan.getStatusCode().is2xxSuccessful();
        audit.logRequest(AuditService.PENEMUAN_ABAIKAN, String.valueOf(id),
                ok ? "temuan #" + id + " (" + medan(balasan, "ip_address")
                     + ") ditandai bukan perangkat kita"
                   : "abaikan temuan #" + id + " DITOLAK: " + alasan(balasan),
                ok, request);
        return balasan;
    }

    // Response-body parsing for audit rows only. Failure to parse must never fail the request.

    private static String medan(ResponseEntity<Object> balasan, String kunci) {
        return (balasan.getBody() instanceof Map<?, ?> m)
                ? String.valueOf(m.get(kunci)) : "?";
    }

    private static String jumlah(ResponseEntity<Object> balasan) {
        return (balasan.getBody() instanceof Map<?, ?> m && m.get("total") instanceof Number n)
                ? String.valueOf(n.intValue()) : "?";
    }

    private static String alasan(ResponseEntity<Object> balasan) {
        String t = (balasan.getBody() instanceof Map<?, ?> m && m.get("detail") != null)
                ? String.valueOf(m.get("detail"))
                : String.valueOf(balasan.getStatusCode());
        return t.length() > 200 ? t.substring(0, 200) : t;
    }
}
