package id.bsp.frontend.repository;

import id.bsp.frontend.entity.NotifLangganan;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

public interface NotifLanggananRepository extends JpaRepository<NotifLangganan, Long> {

    List<NotifLangganan> findByUsername(String username);

    List<NotifLangganan> findByDeviceId(Long deviceId);

    // Subscribers of several devices at once (tiered notifications). One row per (username, device),
    // so callers (NotifikasiInternalController) must dedupe by username to send one email per round.
    List<NotifLangganan> findByDeviceIdIn(List<Long> deviceIds);

    boolean existsByUsernameAndDeviceId(String username, Long deviceId);

    @Transactional
    void deleteByUsernameAndDeviceId(String username, Long deviceId);

    @Transactional
    void deleteByUsername(String username);
}
