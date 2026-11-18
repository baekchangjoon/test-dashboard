package td.minisut;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** 파이프라인 멀티 SUT 검증용 작은 REST 서버. 설명 파일(sut.yaml)만 petclinic과 다르다. */
@SpringBootApplication
public class MiniSutApplication {

    public static void main(String[] args) {
        SpringApplication.run(MiniSutApplication.class, args);
    }
}
