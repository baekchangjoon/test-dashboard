package td.minisut;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Component;

/** 메모리 Bearer 토큰 저장소. 데모 계정은 공개 소스의 기본값이다. */
@Component
public class TokenStore {

    static final String DEMO_USER = "admin";
    static final String DEMO_PASSWORD = "password";

    private final Map<String, String> tokenToUser = new ConcurrentHashMap<>();

    /** 자격 증명이 맞으면 새 토큰을 발급하고, 틀리면 null을 돌려준다. */
    public String issue(String username, String password) {
        if (!DEMO_USER.equals(username) || !DEMO_PASSWORD.equals(password)) {
            return null;
        }
        String token = UUID.randomUUID().toString();
        tokenToUser.put(token, username);
        return token;
    }

    public boolean isValid(String token) {
        return token != null && tokenToUser.containsKey(token);
    }
}
