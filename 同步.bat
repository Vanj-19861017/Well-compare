# 1. 进入你的项目目录
cd /d/python/Person/00-定向井设计工具箱

# 2. 初始化 git 仓库（只需第一次）
git init

# 3. （可选但推荐）创建 .gitignore，排除不需要上传的文件
#    用记事本或编辑器在项目根目录新建 .gitignore 文件，内容见下方

# 4. 添加所有文件到暂存区
git add .

# 5. 提交
git commit -m "first commit: 定向井设计工具箱"

# 6. 把主分支命名为 main（与 GitHub 保持一致）
git branch -M main

# 7. 关联远程仓库
git remote add origin https://github.com/Vanj-19861017/Well-compare.git

# 8. 推送到 GitHub
git push -u origin main