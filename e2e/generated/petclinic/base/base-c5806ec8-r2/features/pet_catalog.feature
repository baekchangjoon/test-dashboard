Feature: Pet catalog

  Scenario: List the available pet types
    When the pet catalog client requests the pet types
    Then the pet catalog response status is 200
    And the pet catalog response is a JSON list
