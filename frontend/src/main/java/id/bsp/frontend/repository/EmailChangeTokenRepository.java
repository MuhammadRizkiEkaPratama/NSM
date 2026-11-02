package id.bsp.frontend.repository;

import id.bsp.frontend.entity.EmailChangeToken;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.transaction.annotation.Transactional;

import java.util.Optional;

public interface EmailChangeTokenRepository extends JpaRepository<EmailChangeToken, Long> {

    Optional<EmailChangeToken> findByToken(String token);

    @Transactional
    void deleteByUsername(String username);
}
