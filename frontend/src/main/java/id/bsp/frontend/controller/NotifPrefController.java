package id.bsp.frontend.controller;

import id.bsp.frontend.dto.DeviceDto;
import id.bsp.frontend.entity.NotifLangganan;
import id.bsp.frontend.repository.NotifLanggananRepository;
import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.security.Principal;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * "My Notifications" page.
 * Each user chooses which devices to receive alerts for. Opt-out by default: no checkmark means no email. The device list comes from Python (owner of device data); subscriptions are stored in Java's MySQL.
 */
@Controller
public class NotifPrefController {

    private final NotifLanggananRepository langganan;
    private final NetmonApiClient api;
    private final AuditService audit;

    public NotifPrefController(NotifLanggananRepository langganan,
                               NetmonApiClient api, AuditService audit) {
        this.langganan = langganan;
        this.api = api;
        this.audit = audit;
    }

    private void isiModel(Model model, String user) {
        List<DeviceDto> devices = api.getDevices();
        Set<Long> subscribed = langganan.findByUsername(user).stream()
                .map(NotifLangganan::getDeviceId)
                .collect(Collectors.toSet());
        model.addAttribute("devices", devices);
        model.addAttribute("subscribed", subscribed);
    }

    @GetMapping("/account/notifikasi")
    public String form(Principal principal, Model model) {
        isiModel(model, principal.getName());
        return "account_notifikasi";
    }

    @PostMapping("/account/notifikasi")
    public String simpan(@RequestParam(name = "device", required = false) List<Long> dipilih,
                         Principal principal, HttpServletRequest request, Model model) {
        String user = principal.getName();
        Set<Long> centang = dipilih == null ? new HashSet<>() : new HashSet<>(dipilih);

        int tambah = 0, hapus = 0;
        // Touch only devices currently in Python's list, so old subscriptions for deleted devices are not disturbed.
        for (DeviceDto d : api.getDevices()) {
            Long id = d.id.longValue();
            boolean mau = centang.contains(id);
            boolean sudah = langganan.existsByUsernameAndDeviceId(user, id);
            if (mau && !sudah) {
                langganan.save(new NotifLangganan(user, id));
                tambah++;
            } else if (!mau && sudah) {
                langganan.deleteByUsernameAndDeviceId(user, id);
                hapus++;
            }
        }

        audit.logRequest(AuditService.NOTIF_PREF, null,
                "ubah langganan notifikasi (+" + tambah + " / -" + hapus + ")",
                true, request);

        isiModel(model, user);
        model.addAttribute("success", "Pengaturan notifikasi disimpan.");
        return "account_notifikasi";
    }
}
