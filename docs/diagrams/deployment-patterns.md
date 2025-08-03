# Mosquitto Charm Deployment Patterns

This document illustrates common deployment patterns and scaling scenarios for the Mosquitto charm.

## Single Instance Deployment

```mermaid
graph TB
    subgraph "Juju Model"
        subgraph "Machine 0"
            CHARM[Mosquitto Charm]
            MOSQUITTO[Mosquitto Service]
            STORAGE[Local Storage]
        end
    end
    
    subgraph "External Clients"
        IOT1[IoT Device 1]
        IOT2[IoT Device 2]
        WEB[Web App]
        APP[MQTT App]
    end
    
    CHARM --> MOSQUITTO
    MOSQUITTO --> STORAGE
    
    IOT1 -->|MQTT| MOSQUITTO
    IOT2 -->|MQTT| MOSQUITTO
    WEB -->|WebSocket| MOSQUITTO
    APP -->|MQTT| MOSQUITTO
    
    style CHARM fill:#e1f5fe
    style MOSQUITTO fill:#e8f5e8
```

```bash
# Deploy single instance
juju deploy mosquitto-operator
juju config mosquitto-operator \
  port=1883 \
  websockets-port=9001 \
  max-connections=1000
```

## High Availability Deployment

```mermaid
graph TB
    subgraph "Juju Model - Primary AZ"
        subgraph "Machine 0"
            CHARM1[Mosquitto Charm]
            MOSQUITTO1[Mosquitto Primary]
            STORAGE1[Persistent Storage]
        end
    end
    
    subgraph "Juju Model - Secondary AZ"
        subgraph "Machine 1"
            CHARM2[Mosquitto Charm]
            MOSQUITTO2[Mosquitto Secondary]
            STORAGE2[Persistent Storage]
        end
    end
    
    subgraph "Load Balancer"
        LB[HAProxy/NGinx]
        VIP[Virtual IP]
    end
    
    subgraph "External Clients"
        CLIENTS[MQTT Clients]
    end
    
    CHARM1 --> MOSQUITTO1
    CHARM2 --> MOSQUITTO2
    MOSQUITTO1 --> STORAGE1
    MOSQUITTO2 --> STORAGE2
    
    CLIENTS --> VIP
    VIP --> LB
    LB --> MOSQUITTO1
    LB --> MOSQUITTO2
    
    STORAGE1 -.->|Sync| STORAGE2
    
    style CHARM1 fill:#e1f5fe
    style CHARM2 fill:#e1f5fe
    style MOSQUITTO1 fill:#e8f5e8
    style MOSQUITTO2 fill:#e8f5e8
    style LB fill:#fff3e0
```

```bash
# Deploy HA setup
juju deploy mosquitto-operator mosquitto-primary \
  --to zone=primary
juju deploy mosquitto-operator mosquitto-secondary \
  --to zone=secondary

# Deploy load balancer
juju deploy haproxy
juju integrate mosquitto-primary haproxy
juju integrate mosquitto-secondary haproxy
```

## Multi-Region Deployment

```mermaid
graph TB
    subgraph "Region A - US East"
        subgraph "AZ-A1"
            M1[Mosquitto-US-1]
        end
        subgraph "AZ-A2"
            M2[Mosquitto-US-2]
        end
        LB_A[Load Balancer A]
    end
    
    subgraph "Region B - EU West"
        subgraph "AZ-B1"
            M3[Mosquitto-EU-1]
        end
        subgraph "AZ-B2"
            M4[Mosquitto-EU-2]
        end
        LB_B[Load Balancer B]
    end
    
    subgraph "Global Traffic Manager"
        GTM[DNS/CDN]
        HEALTH[Health Checks]
    end
    
    subgraph "Clients"
        CLIENT_US[US Clients]
        CLIENT_EU[EU Clients]
        CLIENT_GLOBAL[Global Apps]
    end
    
    M1 --> LB_A
    M2 --> LB_A
    M3 --> LB_B
    M4 --> LB_B
    
    LB_A --> GTM
    LB_B --> GTM
    HEALTH --> GTM
    
    CLIENT_US --> GTM
    CLIENT_EU --> GTM
    CLIENT_GLOBAL --> GTM
    
    GTM -.->|Route| LB_A
    GTM -.->|Route| LB_B
    
    M1 -.->|Bridge| M3
    M2 -.->|Bridge| M4
    
    style M1 fill:#e8f5e8
    style M2 fill:#e8f5e8
    style M3 fill:#e8f5e8
    style M4 fill:#e8f5e8
    style GTM fill:#fff3e0
```

## Edge Computing Deployment

```mermaid
graph TB
    subgraph "Central Cloud"
        subgraph "Core Infrastructure"
            CORE_MQTT[Core Mosquitto Cluster]
            MANAGEMENT[Management Services]
            DATA_STORE[Central Data Store]
        end
    end
    
    subgraph "Edge Location 1"
        subgraph "Edge Node 1"
            EDGE1[Mosquitto Edge 1]
            LOCAL1[Local Storage]
        end
        IOT1[IoT Devices 1]
    end
    
    subgraph "Edge Location 2"
        subgraph "Edge Node 2"
            EDGE2[Mosquitto Edge 2]
            LOCAL2[Local Storage]
        end
        IOT2[IoT Devices 2]
    end
    
    subgraph "Edge Location 3"
        subgraph "Edge Node 3"
            EDGE3[Mosquitto Edge 3]
            LOCAL3[Local Storage]
        end
        IOT3[IoT Devices 3]
    end
    
    EDGE1 --> LOCAL1
    EDGE2 --> LOCAL2
    EDGE3 --> LOCAL3
    
    IOT1 --> EDGE1
    IOT2 --> EDGE2
    IOT3 --> EDGE3
    
    EDGE1 -.->|Bridge| CORE_MQTT
    EDGE2 -.->|Bridge| CORE_MQTT
    EDGE3 -.->|Bridge| CORE_MQTT
    
    CORE_MQTT --> DATA_STORE
    MANAGEMENT --> CORE_MQTT
    
    style CORE_MQTT fill:#e8f5e8
    style EDGE1 fill:#e8f5e8
    style EDGE2 fill:#e8f5e8
    style EDGE3 fill:#e8f5e8
    style MANAGEMENT fill:#e1f5fe
```

```bash
# Deploy edge instances
juju deploy mosquitto-operator mosquitto-edge-1 \
  --constraints "mem=2G cores=1" \
  --to edge-location-1

juju deploy mosquitto-operator mosquitto-edge-2 \
  --constraints "mem=2G cores=1" \
  --to edge-location-2

# Configure for edge workloads
juju config mosquitto-edge-1 \
  max-connections=500 \
  persistence=true \
  message-size-limit=32768
```

## Microservices Integration Pattern

```mermaid
graph TB
    subgraph "Kubernetes Cluster"
        subgraph "Messaging Namespace"
            MOSQUITTO[Mosquitto Charm]
            REDIS[Redis Cache]
            METRICS[Prometheus]
        end
        
        subgraph "Application Namespace"
            API[API Gateway]
            AUTH[Auth Service]
            USERS[User Service]
            ORDERS[Order Service]
            INVENTORY[Inventory Service]
            NOTIFICATIONS[Notification Service]
        end
        
        subgraph "External Services"
            DB[Database]
            QUEUE[Message Queue]
        end
    end
    
    subgraph "External Clients"
        MOBILE[Mobile Apps]
        WEB_APP[Web Applications]
        THIRD_PARTY[Third-party APIs]
    end
    
    MOBILE --> API
    WEB_APP --> API
    THIRD_PARTY --> API
    
    API --> AUTH
    API --> USERS
    API --> ORDERS
    API --> INVENTORY
    
    USERS --> MOSQUITTO
    ORDERS --> MOSQUITTO
    INVENTORY --> MOSQUITTO
    NOTIFICATIONS --> MOSQUITTO
    
    MOSQUITTO --> REDIS
    MOSQUITTO --> METRICS
    
    USERS --> DB
    ORDERS --> DB
    INVENTORY --> DB
    
    NOTIFICATIONS --> QUEUE
    
    style MOSQUITTO fill:#e8f5e8
    style API fill:#e1f5fe
    style AUTH fill:#e1f5fe
    style USERS fill:#e1f5fe
    style ORDERS fill:#e1f5fe
    style INVENTORY fill:#e1f5fe
    style NOTIFICATIONS fill:#e1f5fe
```

## Development and Testing Pattern

```mermaid
graph TB
    subgraph "Development Environment"
        subgraph "Local Development"
            DEV_MOSQUITTO[Dev Mosquitto]
            LOCAL_APP[Local App]
            TEST_CLIENTS[Test Clients]
        end
    end
    
    subgraph "Staging Environment"
        subgraph "Staging Cluster"
            STAGE_MOSQUITTO[Staging Mosquitto]
            STAGE_APPS[Staging Apps]
            LOAD_TESTS[Load Testing]
        end
    end
    
    subgraph "Production Environment"
        subgraph "Prod Cluster"
            PROD_MOSQUITTO[Production Mosquitto]
            PROD_APPS[Production Apps]
            MONITORING[Monitoring Stack]
        end
    end
    
    LOCAL_APP --> DEV_MOSQUITTO
    TEST_CLIENTS --> DEV_MOSQUITTO
    
    STAGE_APPS --> STAGE_MOSQUITTO
    LOAD_TESTS --> STAGE_MOSQUITTO
    
    PROD_APPS --> PROD_MOSQUITTO
    MONITORING --> PROD_MOSQUITTO
    
    DEV_MOSQUITTO -.->|Deploy| STAGE_MOSQUITTO
    STAGE_MOSQUITTO -.->|Promote| PROD_MOSQUITTO
    
    style DEV_MOSQUITTO fill:#e8f5e8
    style STAGE_MOSQUITTO fill:#fff3e0
    style PROD_MOSQUITTO fill:#e8f5e8
```

```bash
# Development setup
juju deploy mosquitto-operator --channel=edge
juju config mosquitto-operator \
  allow-anonymous=true \
  log-level=debug \
  max-connections=100

# Staging setup
juju deploy mosquitto-operator --channel=candidate
juju config mosquitto-operator \
  allow-anonymous=false \
  log-level=notice \
  max-connections=1000

# Production setup
juju deploy mosquitto-operator --channel=stable
juju config mosquitto-operator \
  allow-anonymous=false \
  log-level=warning \
  max-connections=10000 \
  persistence=true
```

## IoT Fleet Management Pattern

```mermaid
graph TB
    subgraph "Central Management"
        FLEET_MGR[Fleet Manager]
        DEVICE_REG[Device Registry]
        POLICY_MGR[Policy Manager]
        CERT_AUTH[Certificate Authority]
    end
    
    subgraph "Regional MQTT Brokers"
        subgraph "Region 1"
            MQTT_R1[Mosquitto Region 1]
            BRIDGE_R1[Bridge Config]
        end
        
        subgraph "Region 2"
            MQTT_R2[Mosquitto Region 2]
            BRIDGE_R2[Bridge Config]
        end
        
        subgraph "Region 3"
            MQTT_R3[Mosquitto Region 3]
            BRIDGE_R3[Bridge Config]
        end
    end
    
    subgraph "Device Groups"
        subgraph "Sensors"
            TEMP[Temperature Sensors]
            HUMID[Humidity Sensors]
            PRESSURE[Pressure Sensors]
        end
        
        subgraph "Actuators"
            PUMPS[Water Pumps]
            VALVES[Control Valves]
            MOTORS[Motors]
        end
        
        subgraph "Gateways"
            GATEWAY1[Edge Gateway 1]
            GATEWAY2[Edge Gateway 2]
            GATEWAY3[Edge Gateway 3]
        end
    end
    
    FLEET_MGR --> DEVICE_REG
    FLEET_MGR --> POLICY_MGR
    POLICY_MGR --> CERT_AUTH
    
    DEVICE_REG --> MQTT_R1
    DEVICE_REG --> MQTT_R2
    DEVICE_REG --> MQTT_R3
    
    MQTT_R1 --> BRIDGE_R1
    MQTT_R2 --> BRIDGE_R2
    MQTT_R3 --> BRIDGE_R3
    
    TEMP --> GATEWAY1
    HUMID --> GATEWAY1
    PRESSURE --> GATEWAY2
    PUMPS --> GATEWAY2
    VALVES --> GATEWAY3
    MOTORS --> GATEWAY3
    
    GATEWAY1 --> MQTT_R1
    GATEWAY2 --> MQTT_R2
    GATEWAY3 --> MQTT_R3
    
    BRIDGE_R1 -.->|Aggregate| FLEET_MGR
    BRIDGE_R2 -.->|Aggregate| FLEET_MGR
    BRIDGE_R3 -.->|Aggregate| FLEET_MGR
    
    style FLEET_MGR fill:#e1f5fe
    style MQTT_R1 fill:#e8f5e8
    style MQTT_R2 fill:#e8f5e8
    style MQTT_R3 fill:#e8f5e8
    style GATEWAY1 fill:#fff3e0
    style GATEWAY2 fill:#fff3e0
    style GATEWAY3 fill:#fff3e0
```

## Security Zones Pattern

```mermaid
graph TB
    subgraph "DMZ Zone"
        subgraph "Edge Security"
            WAF[Web Application Firewall]
            LB[Load Balancer]
            PROXY[Reverse Proxy]
        end
    end
    
    subgraph "Application Zone"
        subgraph "MQTT Services"
            MOSQUITTO[Mosquitto Cluster]
            AUTH_SVC[Authentication Service]
            AUTHZ_SVC[Authorization Service]
        end
        
        subgraph "Supporting Services"
            REDIS[Session Store]
            VAULT[Secret Management]
            MONITOR[Monitoring]
        end
    end
    
    subgraph "Data Zone"
        subgraph "Persistence"
            DB[Database]
            BACKUP[Backup Storage]
            LOGS[Log Storage]
        end
    end
    
    subgraph "Management Zone"
        subgraph "Admin Access"
            BASTION[Bastion Host]
            JUJU[Juju Controller]
            ADMIN[Admin Tools]
        end
    end
    
    subgraph "External"
        CLIENTS[MQTT Clients]
        ADMINS[Administrators]
    end
    
    CLIENTS --> WAF
    WAF --> LB
    LB --> PROXY
    PROXY --> MOSQUITTO
    
    MOSQUITTO --> AUTH_SVC
    MOSQUITTO --> AUTHZ_SVC
    AUTH_SVC --> REDIS
    AUTHZ_SVC --> VAULT
    
    MOSQUITTO --> DB
    MOSQUITTO --> LOGS
    DB --> BACKUP
    
    ADMINS --> BASTION
    BASTION --> JUJU
    JUJU --> MOSQUITTO
    JUJU --> ADMIN
    
    MONITOR --> MOSQUITTO
    MONITOR --> DB
    
    style WAF fill:#ffebee
    style AUTH_SVC fill:#ffebee
    style AUTHZ_SVC fill:#ffebee
    style VAULT fill:#ffebee
    style MOSQUITTO fill:#e8f5e8
    style JUJU fill:#e1f5fe
```

## Performance Scaling Patterns

```mermaid
graph TB
    subgraph "Load Patterns"
        LOW[Low Load\n< 1K connections]
        MEDIUM[Medium Load\n1K - 10K connections]
        HIGH[High Load\n10K - 50K connections]
        EXTREME[Extreme Load\n> 50K connections]
    end
    
    subgraph "Single Instance"
        SINGLE[1 Mosquitto Instance\n2 CPU, 4GB RAM]
    end
    
    subgraph "Horizontal Scale"
        MULTI[Multiple Instances\nLoad Balanced]
        REGION[Regional Distribution]
    end
    
    subgraph "Vertical Scale"
        POWERFUL[High-Performance Instance\n8+ CPU, 16+ GB RAM]
        OPTIMIZED[Kernel Tuning\nNetwork Optimization]
    end
    
    subgraph "Hybrid Scale"
        CLUSTER[Mosquitto Cluster\nMultiple Regions\nOptimized Instances]
    end
    
    LOW --> SINGLE
    MEDIUM --> MULTI
    MEDIUM --> POWERFUL
    HIGH --> REGION
    HIGH --> OPTIMIZED
    EXTREME --> CLUSTER
    
    style LOW fill:#e8f5e8
    style MEDIUM fill:#fff3e0
    style HIGH fill:#ffecb3
    style EXTREME fill:#ffcdd2
    style SINGLE fill:#e1f5fe
    style MULTI fill:#f3e5f5
    style POWERFUL fill:#f3e5f5
    style CLUSTER fill:#f3e5f5
```

These deployment patterns provide guidance for:

1. **Single Instance**: Simple development and small-scale deployments
2. **High Availability**: Production deployments with redundancy
3. **Multi-Region**: Global scale with geographic distribution
4. **Edge Computing**: Distributed IoT and edge scenarios
5. **Microservices**: Integration within modern application architectures
6. **Development/Testing**: Proper environment separation
7. **IoT Fleet**: Large-scale device management
8. **Security Zones**: Defense-in-depth security architecture
9. **Performance Scaling**: Scaling strategies for different load patterns

Each pattern includes specific Juju commands and configuration examples to help implement the deployment approach.