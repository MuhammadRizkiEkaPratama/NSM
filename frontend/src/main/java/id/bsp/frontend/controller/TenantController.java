package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.client.RestClientResponseException;

import java.util.Map;

/**
 * Tenants: who owns which device. Admin only (routes under `/admin`, locked to ROLE_ADMIN by
 * SecurityConfig). Entirely read-only: creating or moving tenants decides who can see what, and
 * cross-tenant leaks fail silently, so that is done through a deliberate migration
 * (`migrate_tenant.py`), not a UI click. Also shows devices with no owner.
 */
@Controller
public class TenantController {

    private final NetmonApiClient api;
    private final AuditService audit;

    public TenantController(NetmonApiClient api, AuditService audit) {
        this.api = api;
        this.audit = audit;
    }

    @GetMapping("/admin/tenant")
    public String halaman(Model model, HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_TENANT, null,
                "buka daftar Tenant", true, request);
        return "tenant";
    }

    @GetMapping("/api/tenant")
    @ResponseBody
    public Object daftar() {
        try {
            return api.getTenant();
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("ok", false, "ditolak", e.getMessage()));
        }
    }
}
