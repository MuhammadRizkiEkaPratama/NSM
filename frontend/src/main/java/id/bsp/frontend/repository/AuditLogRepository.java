package id.bsp.frontend.repository;

import id.bsp.frontend.entity.AuditLog;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface AuditLogRepository extends JpaRepository<AuditLog, Long> {

    /** Search with optional filters (null = ignore). `:q` matches all text columns (actor, action, target, detail, ip). */
    @Query("SELECT a FROM AuditLog a WHERE " +
           "(:action IS NULL OR a.action = :action) AND " +
           "(:actor IS NULL OR a.actor = :actor) AND " +
           "(:tanpaView = false OR a.action NOT LIKE 'VIEW\\_%' ESCAPE '\\') AND " +
           "(:pakaiDaftar = false OR a.action IN :daftar) AND " +
           "(:q IS NULL OR (" +
           "  LOWER(a.actor) LIKE LOWER(CONCAT('%', :q, '%')) OR " +
           "  LOWER(a.action) LIKE LOWER(CONCAT('%', :q, '%')) OR " +
           "  LOWER(COALESCE(a.target, '')) LIKE LOWER(CONCAT('%', :q, '%')) OR " +
           "  LOWER(COALESCE(a.detail, '')) LIKE LOWER(CONCAT('%', :q, '%')) OR " +
           "  LOWER(COALESCE(a.ip, '')) LIKE LOWER(CONCAT('%', :q, '%'))" +
           "))")
    Page<AuditLog> search(@Param("action") String action,
                          @Param("actor") String actor,
                          @Param("q") String q,
                          @Param("tanpaView") boolean tanpaView,
                          @Param("pakaiDaftar") boolean pakaiDaftar,
                          @Param("daftar") List<String> daftar,
                          Pageable pageable);

    /** Count of VIEW_* rows currently hidden, so the page can show the number next to the checkbox. */
    @Query("SELECT COUNT(a) FROM AuditLog a WHERE a.action LIKE 'VIEW\\_%' ESCAPE '\\'")
    long countView();

    @Query("SELECT DISTINCT a.action FROM AuditLog a ORDER BY a.action")
    List<String> distinctActions();

    @Query("SELECT DISTINCT a.actor FROM AuditLog a ORDER BY a.actor")
    List<String> distinctActors();

    /**
     * Latest successful logins for the LDAP management page. Returned raw; LdapController reduces
     * them to the latest per person. NSM only: `audit_logs` does not record E-Canteen logins.
     */
    List<AuditLog> findTop100ByActionOrderByTimestampDesc(String action);
}
