Feature: Pet type catalogue

  Scenario: List the available pet types
    When the pet type catalogue is requested
    Then the pet type catalogue is returned successfully
