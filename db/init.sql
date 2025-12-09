-- ============================================
-- Database: echoverse_app
-- ============================================

CREATE DATABASE IF NOT EXISTS echoverse_app;
USE echoverse_app;

-- ============================================
-- 1. Users
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    avatar VARCHAR(255) DEFAULT NULL,
    bio TEXT DEFAULT NULL,
    role ENUM('user', 'admin') DEFAULT 'user',
    is_verified BOOLEAN DEFAULT FALSE,
    is_blocked BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ============================================
-- 2. Email verification tokens
-- ============================================
CREATE TABLE IF NOT EXISTS email_verification_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    token VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ============================================
-- 3. Password reset tokens
-- ============================================
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    token VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ============================================
-- 4. Posts
-- ============================================
CREATE TABLE IF NOT EXISTS posts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    content TEXT,
    media_path VARCHAR(255),
    media_type ENUM('image','video','audio','file') DEFAULT NULL,
    total_likes INT DEFAULT 0,
    is_blocked BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ============================================
-- 5. Songs (audio files)
-- ============================================
CREATE TABLE IF NOT EXISTS songs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    post_id INT DEFAULT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    file_path VARCHAR(255) NOT NULL,
    duration INT DEFAULT 0, -- seconds
    total_plays INT DEFAULT 0,
    total_likes INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE SET NULL
);

-- ============================================
-- 6. Comments
-- ============================================
CREATE TABLE IF NOT EXISTS comments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    post_id INT DEFAULT NULL,
    song_id INT DEFAULT NULL,
    content TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
    FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ============================================
-- 7. Likes
-- ============================================
CREATE TABLE IF NOT EXISTS likes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    post_id INT DEFAULT NULL,
    song_id INT DEFAULT NULL,
    comment_id INT DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
    FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE,
    FOREIGN KEY (comment_id) REFERENCES comments(id) ON DELETE CASCADE,
    UNIQUE KEY unique_like (user_id, post_id, song_id, comment_id)
);

-- ============================================
-- 8. Follows
-- ============================================
CREATE TABLE IF NOT EXISTS follows (
    id INT AUTO_INCREMENT PRIMARY KEY,
    follower_id INT NOT NULL,
    following_id INT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (follower_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (following_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY unique_follow (follower_id, following_id)
);

-- ============================================
-- 9. User blocks (user-to-user blocking)
-- ============================================
CREATE TABLE IF NOT EXISTS user_blocks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    blocker_id INT NOT NULL,
    blocked_id INT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (blocker_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (blocked_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY unique_block (blocker_id, blocked_id)
);

-- ============================================
-- 10. Admin logs
-- ============================================
CREATE TABLE IF NOT EXISTS admin_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    admin_id INT NOT NULL,
    action VARCHAR(255) NOT NULL,
    target_user_id INT DEFAULT NULL,
    target_post_id INT DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (target_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (target_post_id) REFERENCES posts(id) ON DELETE SET NULL
);

-- ============================================
-- 11. Tags
-- ============================================
CREATE TABLE IF NOT EXISTS tags (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_name (name)
);

-- ============================================
-- 13. Post tags
-- ============================================
CREATE TABLE IF NOT EXISTS post_tags (
    id INT AUTO_INCREMENT PRIMARY KEY,
    post_id INT NOT NULL,
    tag_id INT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE,
    UNIQUE KEY unique_post_tag (post_id, tag_id),
    INDEX idx_post_id (post_id),
    INDEX idx_tag_id (tag_id)
);
-- ============================================
--  Dummy Data: Admin User
-- ============================================
INSERT INTO users (name, email, password_hash, role, is_verified, bio)
VALUES ('Administrator', 'admin@example.com', 'scrypt:32768:8:1$E2gwB2SG3LansyYO$96119ffbd238f0f110217a432ac9a5709dd4f4735b5c64bf8dee00ae9274986faf8c97cf6eedbca3d158be28d8732c3be46a9f675e68c998e14e6e17996e77d3', 'admin', 1, 'System Administrator');

-- ============================================
--  Dummy Data: Regular Users
-- ============================================
INSERT INTO users (name, email, password_hash, role, is_verified, bio) VALUES
('Alice Johnson', 'alice@example.com', 'scrypt:32768:8:1$E2gwB2SG3LansyYO$96119ffbd238f0f110217a432ac9a5709dd4f4735b5c64bf8dee00ae9274986faf8c97cf6eedbca3d158be28d8732c3be46a9f675e68c998e14e6e17996e77d3', 'user', 1, 'Music producer and sound designer'),
('Bob Smith', 'bob@example.com', 'scrypt:32768:8:1$E2gwB2SG3LansyYO$96119ffbd238f0f110217a432ac9a5709dd4f4735b5c64bf8dee00ae9274986faf8c97cf6eedbca3d158be28d8732c3be46a9f675e68c998e14e6e17996e77d3', 'user', 1, 'DJ and beatmaker'),
('Charlie Brown', 'charlie@example.com', 'scrypt:32768:8:1$E2gwB2SG3LansyYO$96119ffbd238f0f110217a432ac9a5709dd4f4735b5c64bf8dee00ae9274986faf8c97cf6eedbca3d158be28d8732c3be46a9f675e68c998e14e6e17996e77d3', 'user', 1, 'Indie artist sharing original tracks'),
('Diana Prince', 'diana@example.com', 'scrypt:32768:8:1$E2gwB2SG3LansyYO$96119ffbd238f0f110217a432ac9a5709dd4f4735b5c64bf8dee00ae9274986faf8c97cf6eedbca3d158be28d8732c3be46a9f675e68c998e14e6e17996e77d3', 'user', 1, 'Electronic music enthusiast'),
('Eve Williams', 'eve@example.com', 'scrypt:32768:8:1$E2gwB2SG3LansyYO$96119ffbd238f0f110217a432ac9a5709dd4f4735b5c64bf8dee00ae9274986faf8c97cf6eedbca3d158be28d8732c3be46a9f675e68c998e14e6e17996e77d3', 'user', 1, 'Singer-songwriter');

-- ============================================
--  Dummy Data: Tags
-- ============================================
INSERT INTO tags (name) VALUES
('music'), ('beats'), ('new'), ('electronic'), ('indie'), ('hiphop'), ('jazz'), ('rock'), ('ambient'), ('chill');

-- ============================================
--  Dummy Data: Posts
-- ============================================
INSERT INTO posts (user_id, content, media_type, total_likes, created_at) VALUES
(2, 'Just finished my latest track! Check it out! #music #new', NULL, 5, DATE_SUB(NOW(), INTERVAL 2 DAY)),
(3, 'Late night studio session vibes #beats #chill', NULL, 12, DATE_SUB(NOW(), INTERVAL 1 DAY)),
(4, 'New indie track dropping soon! Stay tuned! #indie #music', NULL, 8, DATE_SUB(NOW(), INTERVAL 3 DAY)),
(5, 'Electronic vibes for your weekend #electronic #chill', NULL, 15, DATE_SUB(NOW(), INTERVAL 4 DAY)),
(6, 'Acoustic session from yesterday #indie #music', NULL, 7, DATE_SUB(NOW(), INTERVAL 5 DAY)),
(2, 'Working on something special... #new #music', NULL, 3, DATE_SUB(NOW(), INTERVAL 6 DAY)),
(3, 'Hip hop beats that hit different! #hiphop #beats', NULL, 20, DATE_SUB(NOW(), INTERVAL 7 DAY)),
(4, 'Jazz fusion experiment #jazz #music', NULL, 9, DATE_SUB(NOW(), INTERVAL 8 DAY)),
(5, 'Ambient soundscape for relaxation #ambient #chill', NULL, 11, DATE_SUB(NOW(), INTERVAL 9 DAY)),
(6, 'Rock anthem in the making! #rock #new', NULL, 6, DATE_SUB(NOW(), INTERVAL 10 DAY));

-- ============================================
--  Dummy Data: Post Tags
-- ============================================
INSERT INTO post_tags (post_id, tag_id) VALUES
(1, 1), (1, 3),  -- Post 1: music, new
(2, 2), (2, 10),  -- Post 2: beats, chill
(3, 5), (3, 1),  -- Post 3: indie, music
(4, 4), (4, 10),  -- Post 4: electronic, chill
(5, 5), (5, 1),  -- Post 5: indie, music
(6, 3), (6, 1),  -- Post 6: new, music
(7, 6), (7, 2),  -- Post 7: hiphop, beats
(8, 7), (8, 1),  -- Post 8: jazz, music
(9, 9), (9, 10),  -- Post 9: ambient, chill
(10, 8), (10, 3);  -- Post 10: rock, new

-- ============================================
--  Dummy Data: Follows
-- ============================================
INSERT INTO follows (follower_id, following_id) VALUES
(2, 3), (2, 4), (2, 5),
(3, 2), (3, 4),
(4, 2), (4, 3), (4, 5),
(5, 2), (5, 6),
(6, 2), (6, 4);

-- ============================================
--  Dummy Data: Likes
-- ============================================
INSERT INTO likes (user_id, post_id) VALUES
(2, 2), (2, 4), (2, 7),
(3, 1), (3, 5), (3, 9),
(4, 2), (4, 3), (4, 6),
(5, 1), (5, 7), (5, 8),
(6, 2), (6, 4), (6, 9);

-- ============================================
--  Dummy Data: Comments
-- ============================================
INSERT INTO comments (user_id, post_id, content) VALUES
(3, 1, 'This is amazing!'),
(4, 1, 'Love the vibes!'),
(5, 2, 'Great work!'),
(2, 3, 'Can\'t wait to hear more!'),
(6, 4, 'Perfect for my playlist'),
(3, 5, 'Beautiful track!'),
(4, 7, 'This hits different!'),
(5, 8, 'Jazz fusion is the way!'),
(2, 9, 'So relaxing!');