package td.minisut;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final TokenStore tokenStore;

    public AuthController(TokenStore tokenStore) {
        this.tokenStore = tokenStore;
    }

    @PostMapping("/login")
    public ResponseEntity<Map<String, String>> login(@RequestBody Map<String, String> credentials) {
        String token = tokenStore.issue(credentials.get("username"), credentials.get("password"));
        if (token == null) {
            return ResponseEntity.status(401).build();
        }
        return ResponseEntity.ok(Map.of("token", token));
    }
}
