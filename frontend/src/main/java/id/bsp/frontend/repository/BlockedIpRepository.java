package id.bsp.frontend.repository;

import id.bsp.frontend.entity.BlockedIp;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.transaction.annotation.Transactional;

public interface BlockedIpRepository extends JpaRepository<BlockedIp, Long> {

    boolean existsByIp(String ip);

    @Transactional
    void deleteByIp(String ip);
}
