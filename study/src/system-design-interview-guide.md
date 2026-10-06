# System Design Interview Execution & Database Schema Design Masterclass

System design interviews at top technology companies evaluate an engineer's ability to transform ambiguous, high-level product requirements into resilient, scalable, and maintainable software architectures. Anyone can write code that works for ten users, but system design is what enables applications to serve millions of concurrent users reliably. 

When interviewers ask candidates to solve real-time problems, construct database schemas, and formulate database queries, they are testing both high-level distributed systems architecture (HLD) and low-level data modeling precision (LLD). This masterclass provides a complete, step-by-step operational framework to master these interviews.

---

## 1. The Master System Design Interview Execution Framework

Jumping directly into sketching architecture diagrams or selecting branded database products without clarifying scope is the primary reason candidates fail system design evaluations. Interviewers at companies like Google expect candidates to reason about foundational mechanisms rather than relying on vendor-specific black boxes, while companies like Meta differentiate between large-scale distributed infrastructure and product architecture rounds. 

To navigate any system design prompt under time pressure, follow this standardized five-phase execution blueprint.

### Phase 1: Requirement Clarification (Functional vs. Non-Functional)

Begin by explicitly separating the prompt into functional capabilities and non-functional engineering constraints.

1.  **Functional Requirements**: Define the exact features and user capabilities. For an e-commerce system, functional requirements include catalog search, shopping cart management, transactional order checkout, and shipment tracking.
2.  **Non-Functional Requirements**: Quantify system quality attributes. Define concrete target metrics for availability (e.g., 99.99% uptime via Service Level Agreements [SLAs]), latency targets (e.g., $P_{95} < 200\text{ ms}$ for read endpoints), throughput (e.g., 10,000 queries per second [QPS]), data consistency models (strong ACID consistency for financial ledgers versus eventual consistency for social media feeds), and fault tolerance.

### Phase 2: System Scale Classification & Evolution Dynamics

Before choosing hardware or software components, classify the system's operational nature to avoid misallocating infrastructure resources. System evolution follows a predictable five-stage progression:

1.  **Code & Algorithm Optimization (LLD/DSA)**: When an individual server process is slow, optimize internal loop structures, data structures, and object-oriented design patterns before adding hardware.
2.  **Vertical Scaling**: When server resources (CPU, RAM, disk I/O) hit capacity limits, upgrade the single server node's specifications. Vertical scaling has a strict hardware ceiling and cost limit.
3.  **Horizontal Scaling**: When user concurrency and queue lengths exceed single-node limits, add additional stateless application server nodes in parallel.
4.  **Centralized & Distributed Persistence**: As multiple application servers process concurrent requests, transition from local databases to centralized, replicated, and partitioned database clusters to prevent data discrepancy and state drift.
5.  **Load Balancing & Traffic Orchestration**: Introduce an intelligent intermediary—a load balancer—to check node health and distribute incoming client requests evenly across application servers.

#### System Taxonomy: Data-Intensive vs. Compute-Intensive

> **System Taxonomy Rule**: If performance latency is lost in data movement across network, memory, and disk boundaries, the system is **Data-Intensive**. If latency is lost in complex CPU/GPU mathematical execution, the system is **Compute-Intensive**.

*   **Data-Intensive Systems**: Performance is constrained by data volume, ingestion velocity, or retrieval throughput (e.g., Instagram feeds, WhatsApp messaging, banking ledgers). Primary architectural tools include read replicas, multi-layer caching, message brokers, and database sharding.
*   **Compute-Intensive Systems**: Performance is constrained by hardware calculation speed (e.g., video encoding, machine learning inference, simulation engines, cryptographic hashing). Primary architectural tools include GPU/TPU acceleration clusters, parallel execution frameworks, and asynchronous job queues.

### Phase 3: High-Level Architecture (HLD) Design

Sketch the request-response topology across core system boundaries:
*   **Clients**: Web browsers, mobile applications, or third-party API consumers.
*   **DNS & Edge Caching**: Domain Name System resolution and Content Delivery Network (CDN) edge locations for static media assets.
*   **Load Balancers**: Ingress points executing traffic distribution algorithms across backend pools.
*   **Application Services**: Stateless microservice instances executing business domain logic.
*   **Caching Layer**: In-memory data stores (e.g., Redis or Memcached) shielding persistent storage.
*   **Database Tier**: Relational (SQL) or Non-Relational (NoSQL) stores maintaining persistent application state.
*   **Asynchronous Processing Tier**: Message queues and Pub/Sub brokers decoupling long-running background tasks.

### Phase 4: Database Schema Preparation & SQL Query Construction

Model the core domain entities, select appropriate storage engines (RDBMS vs. NoSQL), establish cardinalities (1:1, 1:N, N:M junction tables), enforce relational integrity constraints, write core database queries, and design composite indexes for high-frequency access patterns.

### Phase 5: Deep Dive, Bottleneck Analysis, and Architectural Trade-offs

Proactively analyze system failure domains. Address horizontal scaling limits, single points of failure (SPOFs), cache eviction strategies, database replication lag, partitioning mechanics, and CAP theorem trade-offs.

---

## 2. Methodical Database Schema & Query Design Protocol

Designing a database schema during an interview requires a repeatable, five-step engineering protocol that guarantees structural correctness, data integrity, and optimal query execution.

### Step 1: Entity Extraction & Attribute Identification

Extract key domain nouns from the functional requirements. For each entity, declare its core attributes and scalar data types. In a social messaging context, primary entities include `users`, `conversations`, and `messages`.

### Step 2: Cardinality & Relationship Mapping

Define how entities relate to one another:
*   **One-to-One (1:1)**: A user has one user profile preference record. Implemented via a shared Primary Key or a Foreign Key with a `UNIQUE` constraint.
*   **One-to-Many (1:N)**: A user author's multiple posts. Implemented by placing a Foreign Key on the child table (`posts`) referencing the parent table's Primary Key (`users`).
*   **Many-to-Many (N:M)**: Students enroll in multiple courses, and courses contain multiple students. Implemented by constructing a **Junction Table** (associative table) containing foreign keys referencing both primary entity tables.

### Step 3: Storage Paradigm Selection (SQL vs. NoSQL)

Select the database engine based on data structure flexibility and transactional guarantees:

| Feature / Metric | Relational SQL (e.g., PostgreSQL, MySQL) | Non-Relational NoSQL (e.g., MongoDB, Cassandra, DynamoDB) |
| :--- | :--- | :--- |
| **Data Structure** | Rigid, predefined tabular schema with strict rows and columns. | Flexible, schemaless documents, key-value pairs, columnar, or graph nodes. |
| **Transactional Integrity** | Strong ACID compliance (Atomicity, Consistency, Isolation, Durability). | BASE compliance (Basically Available, Soft-state, Eventual consistency). |
| **Scaling Mechanics** | Primarily vertical; horizontal scaling requires read replicas and complex sharding. | Built natively for horizontal cluster partitioning and seamless node scaling. |
| **Optimal Use Cases** | Financial ledgers, e-commerce checkouts, payment processing, complex multi-table JOINs. | High-volume clickstreams, real-time telemetry, unstructured user content, flexible user profiles. |

### Step 4: DDL Schema Definition & Integrity Constraints

Write explicit Data Definition Language (DDL) code applying standard integrity constraints:
*   `PRIMARY KEY`: Guarantees unique record identification and automatically builds a clustered index.
*   `FOREIGN KEY`: Enforces referential integrity between child and parent tables.
*   `UNIQUE`: Prevents duplicate entries across non-primary columns (e.g., `email`, `username`).
*   `NOT NULL`: Mandatory field requirement preventing null value insertions.
*   `CHECK`: Enforces domain-specific validation rules (e.g., `price >= 0` or `status IN ('PENDING', 'PAID')`).
*   `DEFAULT`: Supplies fallback values for optional attributes.

### Step 5: Query Optimization, Indexing, and Pagination

Construct Data Manipulation Language (DML) queries and design indexing strategies:
*   **B-Tree Indexes**: Default tree structure optimized for equality (`=`) and range queries (`<`, `>`, `BETWEEN`).
*   **Composite Indexes**: Multi-column indexes constructed following the **Leftmost Prefix Rule** for queries filtering on multiple attributes simultaneously (e.g., `INDEX (user_id, created_at)`).
*   **Cursor-Based Pagination**: Avoid offset-based pagination (`OFFSET 10000`) on large datasets due to $O(N)$ sequential row scanning overhead. Implement keyset/cursor pagination filtering on indexed sequential attributes (`WHERE id < last_seen_id ORDER BY id DESC LIMIT 20`).

---

## 3. Case Study 1: Real-Time Social Messaging System (e.g., Messenger / WhatsApp)

Real-time communication platforms require ultra-low-latency message processing, persistent bi-directional connection management, and cursor-based history retrieval.

### System Requirements & Constraints

*   **Functional Requirements**: Users can establish 1-on-1 conversations, send real-time text messages, and query paginated chat history.
*   **Non-Functional Metrics**: Message delivery latency $P_{99} < 100\text{ ms}$; high availability; write-heavy payload ($10\text{M}+$ daily messages); cursor-based message history retrieval.

### Database Schema Definition (DDL)

```sql
-- User Entity Table
CREATE TABLE users (
    user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Conversation Entity Table
CREATE TABLE conversations (
    conversation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    is_group BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Conversation Participants Junction Table (N:M Relationship)
CREATE TABLE conversation_participants (
    conversation_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (conversation_id, user_id),
    CONSTRAINT fk_part_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    CONSTRAINT fk_part_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Message Entity Table
CREATE TABLE messages (
    message_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id BIGINT NOT NULL,
    sender_id BIGINT NOT NULL,
    message_body TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_msg_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    CONSTRAINT fk_msg_sender FOREIGN KEY (sender_id) REFERENCES users(user_id) ON DELETE SET NULL
);

-- Composite B-Tree Index for Efficient Cursor Pagination on Chat History
CREATE INDEX idx_messages_conversation_time 
ON messages (conversation_id, created_at DESC, message_id DESC);
```

### Core SQL Queries

#### 1. Inserting a New Real-Time Message

```sql
INSERT INTO messages (conversation_id, sender_id, message_body)
VALUES (42, 1001, 'Hello, let us review the system architecture draft.')
RETURNING message_id, created_at;
```

#### 2. Fetching Chat History via Cursor Pagination

```sql
SELECT 
    m.message_id,
    m.sender_id,
    u.username AS sender_name,
    m.message_body,
    m.created_at
FROM messages m
INNER JOIN users u ON m.sender_id = u.user_id
WHERE m.conversation_id = 42
  AND m.created_at < '2026-10-06 02:00:00+00' -- Cursor timestamp
ORDER BY m.created_at DESC, m.message_id DESC
LIMIT 20;
```

### Real-Time Architecture & Data Flow

> **Architecture Flow**: Clients maintain persistent WebSocket channels with stateless WebSocket Gateway instances. A centralized Redis session store maps active `user_id` locations to specific Gateway instances. When a message is sent, the receiving Gateway writes directly to persistent database storage and pushes the event to an asynchronous message broker (e.g., Apache Kafka or RabbitMQ). The broker routes the payload to the recipient's connected Gateway for immediate push delivery. Platforms like X (Twitter) leverage Write-Around Caching (WAC) to write tweets directly to persistent databases while serving timeline reads from Redis.

---

## 4. Case Study 2: High-Throughput E-Commerce Order Processing (e.g., Amazon / Swiggy)

Transactional order management systems require strict ACID guarantees to maintain absolute financial consistency and prevent inventory overselling during concurrent traffic surges.

### System Requirements & Constraints

*   **Functional Requirements**: Customers add items to cart, checkout with atomic inventory reservation, process payments, and track order execution status.
*   **Non-Functional Metrics**: Absolute ACID compliance; zero double-booking or stock overselling; high availability during 10x flash-sale surges; asynchronous fault-tolerant status tracking.

### Database Schema Definition (DDL)

```sql
-- Products Table
CREATE TABLE products (
    product_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_name VARCHAR(255) NOT NULL,
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    stock_quantity INT NOT NULL CHECK (stock_quantity >= 0),
    version INT DEFAULT 1 NOT NULL -- Used for Optimistic Concurrency Control
);

-- Orders Table
CREATE TABLE orders (
    order_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL,
    total_amount NUMERIC(10, 2) NOT NULL CHECK (total_amount >= 0),
    order_status VARCHAR(30) DEFAULT 'PENDING' NOT NULL 
        CHECK (order_status IN ('PENDING', 'PAID', 'CANCELLED', 'SHIPPED', 'DELIVERED')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Order Items Junction Table (N:M Products to Orders)
CREATE TABLE order_items (
    order_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    quantity INT NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    PRIMARY KEY (order_id, product_id),
    CONSTRAINT fk_items_order FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
    CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE INDEX idx_orders_user_status ON orders (user_id, order_status);
```

### Core Queries & Transactional Logic

#### Atomic Inventory Deduction & Order Creation

```sql
BEGIN;

-- Step 1: Lock product row to inspect inventory (Pessimistic Locking)
SELECT stock_quantity 
FROM products 
WHERE product_id = 501 
FOR UPDATE;

-- Step 2: Deduct stock atomically with non-negative validation
UPDATE products 
SET stock_quantity = stock_quantity - 2 
WHERE product_id = 501 AND stock_quantity >= 2;

-- Step 3: Create order record
INSERT INTO orders (user_id, total_amount, order_status)
VALUES (1001, 299.98, 'PENDING')
RETURNING order_id;

-- Step 4: Create order item record
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
VALUES (9001, 501, 2, 149.99);

COMMIT;
```

### Asynchronous Event-Driven Order Pipeline

> **Architecture Flow**: Order checkout executes synchronously within an ACID relational transaction. Once persisted, the Order Service emits an `OrderCreated` event to an asynchronous message broker (e.g., RabbitMQ). Downstream workers (Payment Service, Inventory Fulfillment, Notification Service) subscribe to the topic to process fulfillment independently. Real-time food delivery applications like Swiggy and Zomato utilize Write-Back Caching (WBC) for order status updates, writing high-frequency status changes directly to memory first and flushing asynchronously to persistent storage. Unprocessable messages are automatically routed to a Dead Letter Queue (DLQ) after $N$ retry attempts.

---

## 5. Case Study 3: Adaptive Video Streaming Platform (e.g., YouTube / Prime Video)

Video platforms handle compute-heavy binary upload and transcoding workflows alongside data-heavy, ultra-low-latency media playback across heterogeneous client networks.

### System Requirements & Constraints

*   **Functional Requirements**: Content creators upload source video binaries; processing pipelines transcode media into multiple resolution renditions; viewers stream video via Adaptive Bit-Rate (ABR) protocols.
*   **Non-Functional Metrics**: Playback startup latency $P_{95} < 500\text{ ms}$; zero buffering during playback; global distribution via edge CDNs; compute-bound encoding cluster isolation.

### Database Schema Definition (DDL)

```sql
-- Video Metadata Table
CREATE TABLE videos (
    video_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uploader_id BIGINT NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    duration_seconds INT NOT NULL CHECK (duration_seconds > 0),
    video_status VARCHAR(20) DEFAULT 'PROCESSING' NOT NULL 
        CHECK (video_status IN ('UPLOADING', 'PROCESSING', 'READY', 'FAILED')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Video Renditions Table (1:N Video to Transcoded Resolutions)
CREATE TABLE video_renditions (
    rendition_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    video_id BIGINT NOT NULL,
    resolution VARCHAR(10) NOT NULL CHECK (resolution IN ('240p', '480p', '720p', '1080p', '4K')),
    bitrate_kbps INT NOT NULL CHECK (bitrate_kbps > 0),
    segment_manifest_url VARCHAR(1024) NOT NULL,
    file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes > 0),
    CONSTRAINT fk_rendition_video FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE INDEX idx_renditions_video_res ON video_renditions (video_id, resolution);
```

### Core SQL Queries

```sql
-- Retrieve all transcoded renditions for manifest file construction
SELECT 
    resolution,
    bitrate_kbps,
    segment_manifest_url
FROM video_renditions
WHERE video_id = 8801
ORDER BY bitrate_kbps DESC;
```

### Compute & Storage Architecture

> **Architecture Flow**: Creators upload video binaries directly to Object Storage (e.g., AWS S3) via pre-signed URLs, completely bypassing application API servers. Object creation events trigger asynchronous transcoding tasks on a priority queue. Distributed GPU worker pools slice source video into short 2-to-10-second segments and encode them across multiple resolutions (1080p, 720p, 480p) using standard codecs (H.264/AV1). Transcoded segments are pushed to global CDN edge locations. Video players retrieve an HLS/DASH manifest file, sample local network throughput, and dynamically request matching bit-rate segments via Adaptive Bit-Rate (ABR) algorithms.

---

## 6. Distributed System Building Blocks & Interview Reference

### Load Balancing Algorithms

Load balancers sit between clients and backend pools to prevent hardware bottlenecks:

*   **Round Robin**: Sequentially distributes requests. Stateless and simple, but ignores server hardware capacity variations.
*   **Weighted Round Robin**: Assigns capacity weights to servers based on hardware specs (CPU/RAM), distributing requests proportionally.
*   **Least Connections**: Directs traffic to the server with the fewest active connections. Ideal for long-lived WebSocket sessions.
*   **Least Response Time**: Directs requests to the node exhibiting the lowest average latency and fewest active connections.
*   **IP Hash**: Hashes the client IP address to consistently map the user to a specific backend instance.
*   **Geo-Based Routing**: Routes traffic to the physical data center geographically closest to the client origin IP address.

### Caching Strategies & Eviction Policies

#### Caching Strategies

*   **Read-Through**: Application queries cache. On cache miss, the cache fetches state from the database, populates memory, and returns state to caller.
*   **Write-Through**: Application writes to cache; cache synchronously updates the database before completing.
*   **Write-Around (WAC)**: Application writes directly to persistent database, bypassing cache. State enters cache only upon subsequent read queries. Prevents cache pollution on write-heavy applications (e.g., X / Twitter).
*   **Write-Back / Write-Behind (WBC)**: Application writes to cache; cache acknowledges immediately. Updates flush to persistent database asynchronously. Provides ultra-low write latency but risks data loss during ungraceful cache failure (e.g., Swiggy/Zomato order tracking).

#### Eviction Policies

*   **Least Recently Used (LRU)**: Evicts items unaccessed for the longest time interval.
*   **Most Recently Used (MRU)**: Evicts items accessed most recently (useful when older items are more likely to be re-read).
*   **Least Frequently Used (LFU)**: Tracks access frequency counts and evicts items with lowest access counts.
*   **First-In, First-Out (FIFO)**: Evicts items in exact order of insertion.

### Asynchronous Messaging Topologies

*   **Point-to-Point Queue**: Producers publish messages to a queue; a single worker process consumes and executes each task.
*   **Publish/Subscribe (Pub/Sub)**: Producers publish message events to a topic; all subscribed service workers receive independent copies.
*   **Dead Letter Queue (DLQ)**: Catches corrupted or unprocessable messages ("poison messages") after $N$ failed retries, allowing operator inspection without stalling primary processing queues.

### Database Replication & Sharding Mechanics

#### Replication Topologies

*   **Single-Leader**: Writes target a single Primary node. Primary streams WAL update logs to Read Replicas synchronously or asynchronously.
*   **Multi-Leader**: Multiple Primary nodes across distinct data centers accept writes simultaneously. Conflicts are resolved via Last-Write-Wins (LWW), Replica ID hierarchy, or application-level merges.
*   **Leaderless**: Writes and reads execute across $N$ nodes simultaneously. Relies on **Quorum Consensus** where $R + W > N$ ($R$ = Read quorum, $W$ = Write quorum, $N$ = Total replicas) to guarantee read-write overlap.

#### Sharding Strategies

*   **Key-Range Partitioning**: Assigns contiguous key ranges to specific shard nodes. Enables efficient range queries, but creates write hotspots if keys cluster around specific ranges (e.g., timestamps).
*   **Hash-Based Partitioning**: Passes partition keys through a hash function (`hash(user_id) % num_shards`) to distribute writes evenly across shards.
*   **Secondary Indexes**: Local Secondary Indexes (Document-Partitioned) require **Scatter-Gather Reads** across all shards. Global Secondary Indexes (Term-Partitioned) eliminate scatter-gather reads but add latency to writes.

### CAP Theorem & Real-World Tech Stack Mapping

Under a network partition ($P$), distributed systems must trade off between Consistency ($C$) and Availability ($A$).

*   **CP Systems (Consistency + Partition Tolerance)**: Rejects reads/writes if nodes cannot synchronize, prioritizing absolute data consistency (e.g., banking transactions, inventory reservation).
*   **AP Systems (Availability + Partition Tolerance)**: Accepts reads/writes during network partitions, returning stale state if necessary and converging eventually (e.g., social media feeds, live comment streams).

#### Industry Database Selection Mapping

*   **Apache Cassandra**: Distributed columnar store used by Netflix for high-throughput user activity logging and view history.
*   **Amazon DynamoDB**: Managed NoSQL database used by Amazon for seamless horizontal scaling during peak sales events.
*   **HBase**: Columnar store used by Meta for high-volume messaging and activity logs.
*   **Redis**: High-speed in-memory key-value store used by X (Twitter) for timeline caching and session state.

---

## 7. System Design Interview Execution Checklist

1.  **Do Not Start By Drawing Components**: Spend the first 5 minutes clarifying Functional Requirements, Non-Functional Metrics ($P_{95}/P_{99}$ latency SLAs, QPS), and scale constraints.
2.  **Classify System Taxonomy Early**: State explicitly whether the system is **Data-Intensive** or **Compute-Intensive** to justify infrastructure choices.
3.  **Execute Structured Data Modeling**: Extract entities, establish cardinalities, write clean DDL schemas with explicit constraints (`PRIMARY KEY`, `FOREIGN KEY`, `UNIQUE`, `NOT NULL`, `CHECK`), and define B-Tree or Composite indexes for high-frequency access patterns.
4.  **Eliminate OFFSET Pagination**: Implement cursor-based/keyset pagination for large tabular datasets.
5.  **Address Distributed Failure Modes**: Explicitly discuss Single Points of Failure (SPOFs), cache eviction policies, message queue Dead Letter Queues (DLQs), database replication lag, and CAP theorem trade-offs.
