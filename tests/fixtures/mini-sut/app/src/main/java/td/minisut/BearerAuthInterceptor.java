package td.minisut;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/** /api/** 요청에 Bearer 토큰을 요구한다. 없거나 틀리면 401. 서블릿 안(DispatcherServlet)에서 거부하므로 거부된 TC도 귀속된다. */
@Component
public class BearerAuthInterceptor implements HandlerInterceptor {

    private static final String PREFIX = "Bearer ";

    private final TokenStore tokenStore;

    public BearerAuthInterceptor(TokenStore tokenStore) {
        this.tokenStore = tokenStore;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        String header = request.getHeader("Authorization");
        String token = header != null && header.startsWith(PREFIX) ? header.substring(PREFIX.length()) : null;
        if (tokenStore.isValid(token)) {
            return true;
        }
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        return false;
    }
}
