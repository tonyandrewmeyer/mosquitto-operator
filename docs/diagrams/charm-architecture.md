# Mosquitto Charm Architecture Diagrams

This document provides visual diagrams explaining the Mosquitto charm architecture, event flows, and component interactions.

## Overall Charm Architecture

```mermaid
graph TB
    subgraph "Juju Controller"
        J[Juju Agent]
    end
    
    subgraph "Mosquitto Charm Unit"
        subgraph "Charm Process"
            C[MosquittoOperatorCharm]
            CFG[MosquittoConfig]
            ACTIONS[Action Classes]
        end
        
        subgraph "Workload Module"
            M[mosquitto.py]
            INSTALL[install()]
            CONFIGURE[configure()]
            START[start()]
            STOP[stop()]
            STATUS[get_status()]
        end
    end
    
    subgraph "System Services"
        APT[APT Package Manager]
        SYSTEMD[SystemD]
        MOSQUITTO[Mosquitto Service]
    end
    
    subgraph "File System"
        CONFIG[/etc/mosquitto/mosquitto.conf]
        DATA[/var/lib/mosquitto/]
        LOGS[/var/log/mosquitto/]
    end
    
    J -->|Hook Events| C
    C -->|Configuration| CFG
    C -->|Workload Operations| M
    M -->|Package Management| APT
    M -->|Service Control| SYSTEMD
    SYSTEMD -->|Manages| MOSQUITTO
    M -->|Writes Config| CONFIG
    MOSQUITTO -->|Reads Config| CONFIG
    MOSQUITTO -->|Stores Data| DATA
    MOSQUITTO -->|Writes Logs| LOGS
    
    style C fill:#e1f5fe
    style M fill:#f3e5f5
    style MOSQUITTO fill:#e8f5e8
```

## Charm Event Lifecycle

```mermaid
sequenceDiagram
    participant J as Juju Controller
    participant C as MosquittoOperatorCharm
    participant M as mosquitto.py
    participant S as System (APT/SystemD)
    participant MS as Mosquitto Service
    
    Note over J,MS: Install Event
    J->>C: install event
    C->>C: set status: "installing Mosquitto"
    C->>M: install()
    M->>S: apt update && apt install mosquitto
    M->>S: create directories
    M->>S: set ownership
    M-->>C: installation complete
    
    Note over J,MS: Start Event
    J->>C: start event
    C->>C: set status: "starting Mosquitto"
    C->>C: _get_mosquitto_config()
    C->>M: configure(config)
    M->>S: write /etc/mosquitto/mosquitto.conf
    M->>S: set file permissions
    C->>M: start()
    M->>S: systemctl enable mosquitto
    M->>S: systemctl start mosquitto
    M->>M: _wait_for_service()
    M-->>C: service ready
    C->>M: get_version()
    M-->>C: version string
    C->>C: set_workload_version()
    C->>C: set status: "Mosquitto is running"
    
    Note over J,MS: Config Changed Event
    J->>C: config-changed event
    C->>C: set status: "updating configuration"
    C->>C: _get_mosquitto_config()
    C->>M: configure(config)
    M->>S: write new config file
    C->>M: restart()
    M->>S: systemctl restart mosquitto
    M->>M: _wait_for_service()
    M-->>C: service ready
    C->>C: set status: "Mosquitto is running"
```

## Configuration Flow

```mermaid
graph LR
    subgraph "Juju Config"
        P[port: 1883]
        WP[websockets-port: 9001]
        MC[max-connections: -1]
        AA[allow-anonymous: false]
        LL[log-level: notice]
        PERS[persistence: true]
        MSL[message-size-limit: 268435456]
    end
    
    subgraph "Charm Processing"
        GC[_get_mosquitto_config()]
        DC[MosquittoConfig dataclass]
    end
    
    subgraph "Workload Module"
        CONF[configure()]
        GEN[_generate_config()]
    end
    
    subgraph "Mosquitto Config File"
        CF["/etc/mosquitto/mosquitto.conf"]
        PORT["port 1883"]
        LOG["log_dest file /var/log/mosquitto/mosquitto.log"]
        LOGTYPE["log_type notice"]
        PERSIST["persistence true"]
        LISTENER["listener 9001\nprotocol websockets"]
    end
    
    P --> GC
    WP --> GC
    MC --> GC
    AA --> GC
    LL --> GC
    PERS --> GC
    MSL --> GC
    
    GC --> DC
    DC --> CONF
    CONF --> GEN
    GEN --> CF
    
    CF --> PORT
    CF --> LOG
    CF --> LOGTYPE
    CF --> PERSIST
    CF --> LISTENER
    
    style DC fill:#e1f5fe
    style CF fill:#e8f5e8
```

## Action Execution Flow

```mermaid
graph TD
    subgraph "Juju User"
        U[User runs: juju run mosquitto-operator/0 restart]
    end
    
    subgraph "Juju Controller"
        J[Juju Agent]
    end
    
    subgraph "Charm Process"
        C[MosquittoOperatorCharm]
        AE[_on_restart_action()]
        ASE[_on_get_status_action()]
    end
    
    subgraph "Workload Module"
        R[restart()]
        GS[get_status()]
    end
    
    subgraph "System"
        SYS[systemctl restart mosquitto]
        WAIT[_wait_for_service()]
        STATUS[systemctl status checks]
    end
    
    U -->|Action Request| J
    J -->|restart_action event| C
    C --> AE
    AE --> R
    R --> SYS
    R --> WAIT
    WAIT -->|Service Ready| AE
    AE -->|set_results()| C
    C -->|Action Results| J
    J -->|Response| U
    
    U -->|Status Request| J
    J -->|get_status_action event| C
    C --> ASE
    ASE --> GS
    GS --> STATUS
    STATUS -->|Status Dict| ASE
    ASE -->|set_results()| C
    
    style AE fill:#fff3e0
    style ASE fill:#fff3e0
    style R fill:#f3e5f5
    style GS fill:#f3e5f5
```

## Service Management Architecture

```mermaid
graph TB
    subgraph "Mosquitto Charm Control"
        CHARM[MosquittoOperatorCharm]
        WM[mosquitto.py workload module]
    end
    
    subgraph "System Integration Layer"
        APT[APT Package Manager]
        SYSTEMD[SystemD Service Manager]
        FS[File System Operations]
    end
    
    subgraph "Mosquitto Service Stack"
        MS[Mosquitto Service Process]
        CONFIG[Configuration Files]
        DATA[Persistent Data]
        LOGS[Log Files]
    end
    
    subgraph "Network Interfaces"
        MQTT[MQTT Port 1883]
        WS[WebSocket Port 9001]
    end
    
    subgraph "External Clients"
        IOT[IoT Devices]
        WEB[Web Applications]
        APPS[MQTT Applications]
    end
    
    CHARM -->|Workload Operations| WM
    WM -->|Package Management| APT
    WM -->|Service Control| SYSTEMD
    WM -->|File Operations| FS
    
    APT -->|Installs/Updates| MS
    SYSTEMD -->|Controls| MS
    FS -->|Manages| CONFIG
    FS -->|Manages| DATA
    FS -->|Manages| LOGS
    
    MS -->|Reads| CONFIG
    MS -->|Stores Messages| DATA
    MS -->|Writes| LOGS
    MS -->|Listens on| MQTT
    MS -->|Listens on| WS
    
    IOT -->|MQTT Protocol| MQTT
    WEB -->|MQTT over WebSocket| WS
    APPS -->|MQTT Protocol| MQTT
    
    style CHARM fill:#e1f5fe
    style WM fill:#f3e5f5
    style MS fill:#e8f5e8
    style MQTT fill:#fff3e0
    style WS fill:#fff3e0
```

## Error Handling and Status Flow

```mermaid
stateDiagram-v2
    [*] --> Maintenance: Event Received
    
    state Maintenance {
        [*] --> Installing: install event
        [*] --> Starting: start event
        [*] --> Updating: config-changed event
        [*] --> Stopping: stop event
    }
    
    Installing --> CheckInstall: mosquitto.install()
    CheckInstall --> Active: Success
    CheckInstall --> Error: Installation Failed
    
    Starting --> Configure: mosquitto.configure()
    Configure --> StartService: mosquitto.start()
    StartService --> WaitReady: _wait_for_service()
    WaitReady --> SetVersion: get_version()
    SetVersion --> Active: Success
    StartService --> Error: Start Failed
    WaitReady --> Error: Timeout (30s)
    
    Updating --> Configure: mosquitto.configure()
    Configure --> RestartService: mosquitto.restart()
    RestartService --> WaitReady: _wait_for_service()
    RestartService --> Error: Restart Failed
    
    Stopping --> StopService: mosquitto.stop()
    StopService --> [*]: Success
    StopService --> Error: Stop Failed
    
    Active --> Maintenance: New Event
    Error --> Maintenance: Manual Intervention
    
    state Active {
        [*] --> Running: "Mosquitto is running"
        Running --> ActionExecuted: Action Completed
        ActionExecuted --> Running: Continue
    }
    
    state Error {
        [*] --> ErrorState: Set Error Status
        ErrorState --> [*]: Requires Manual Fix
    }
```

## Data Flow and Persistence

```mermaid
graph LR
    subgraph "Configuration Sources"
        JC[Juju Config]
        DEFAULTS[Charm Defaults]
    end
    
    subgraph "Configuration Processing"
        MC[MosquittoConfig]
        GEN[_generate_config()]
    end
    
    subgraph "File System"
        CONF[/etc/mosquitto/mosquitto.conf]
        DATA[/var/lib/mosquitto/]
        LOGS[/var/log/mosquitto/]
    end
    
    subgraph "Mosquitto Service"
        PROC[Mosquitto Process]
        MEM[In-Memory State]
        PERSIST[Persistence Engine]
    end
    
    subgraph "External Interfaces"
        CLIENT[MQTT Clients]
        DISK[Persistent Storage]
        SYSLOG[System Logs]
    end
    
    JC --> MC
    DEFAULTS --> MC
    MC --> GEN
    GEN --> CONF
    
    CONF --> PROC
    PROC --> MEM
    PROC --> PERSIST
    PERSIST --> DATA
    PROC --> LOGS
    
    CLIENT <--> MEM
    DATA <--> DISK
    LOGS --> SYSLOG
    
    style MC fill:#e1f5fe
    style PROC fill:#e8f5e8
    style DATA fill:#fff3e0
```

## Testing Architecture

```mermaid
graph TB
    subgraph "Test Types"
        UT[Unit Tests]
        IT[Integration Tests]
    end
    
    subgraph "Unit Testing (ops.testing)"
        CTX[testing.Context]
        STATE[testing.State]
        RUN[ctx.run()]
        ASSERT[Assertions]
    end
    
    subgraph "Integration Testing (Jubilant)"
        TM[temp_model()]
        DEPLOY[juju.deploy()]
        CONFIG[juju.config()]
        ACTION[juju.run_action()]
        VERIFY[MQTT Client Tests]
    end
    
    subgraph "Test Coverage"
        EVENTS[Event Handlers]
        ACTIONS[Action Methods]
        WORKLOAD[mosquitto.py Functions]
        CONFIG_TESTS[Configuration Scenarios]
    end
    
    UT --> CTX
    CTX --> STATE
    STATE --> RUN
    RUN --> ASSERT
    
    IT --> TM
    TM --> DEPLOY
    DEPLOY --> CONFIG
    CONFIG --> ACTION
    ACTION --> VERIFY
    
    ASSERT --> EVENTS
    ASSERT --> ACTIONS
    VERIFY --> WORKLOAD
    VERIFY --> CONFIG_TESTS
    
    style UT fill:#e8f5e8
    style IT fill:#e1f5fe
    style VERIFY fill:#fff3e0
```

## Network and Security Model

```mermaid
graph TB
    subgraph "External Network"
        CLIENTS[MQTT Clients]
        WEB_CLIENTS[Web Clients]
        IOT[IoT Devices]
    end
    
    subgraph "Network Layer"
        FW[Firewall Rules]
        LB[Load Balancer]
    end
    
    subgraph "Mosquitto Service"
        MQTT_PORT[Port 1883 - MQTT]
        WS_PORT[Port 9001 - WebSockets]
        AUTH[Authentication]
        AUTHZ[Authorization]
    end
    
    subgraph "Security Controls"
        ANON[allow-anonymous: false]
        CONN_LIMIT[max-connections]
        MSG_LIMIT[message-size-limit]
        LOGGING[Security Logging]
    end
    
    subgraph "Data Protection"
        PERSIST[Message Persistence]
        BACKUP[Data Backup]
        LOGS[Audit Logs]
    end
    
    CLIENTS --> FW
    WEB_CLIENTS --> FW
    IOT --> FW
    
    FW --> LB
    LB --> MQTT_PORT
    LB --> WS_PORT
    
    MQTT_PORT --> AUTH
    WS_PORT --> AUTH
    AUTH --> AUTHZ
    
    AUTHZ --> ANON
    AUTHZ --> CONN_LIMIT
    AUTHZ --> MSG_LIMIT
    AUTHZ --> LOGGING
    
    LOGGING --> LOGS
    AUTHZ --> PERSIST
    PERSIST --> BACKUP
    
    style AUTH fill:#ffebee
    style AUTHZ fill:#ffebee
    style ANON fill:#fff3e0
    style LOGGING fill:#e8f5e8
```

These diagrams provide a comprehensive visual understanding of:

1. **Overall Architecture**: How components interact within the charm
2. **Event Lifecycle**: Step-by-step event processing flow
3. **Configuration Flow**: How Juju config becomes Mosquitto config
4. **Action Execution**: How user actions are processed
5. **Service Management**: Integration with system services
6. **Error Handling**: State transitions and error scenarios
7. **Data Flow**: Configuration and persistence patterns
8. **Testing Architecture**: Unit and integration test approaches
9. **Network Security**: Security controls and network topology

Each diagram uses consistent color coding:
- Light blue: Charm/Ops framework components
- Light purple: Workload/application logic
- Light green: External services/processes
- Light orange: Network interfaces/actions
- Light red: Security components